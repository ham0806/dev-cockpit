"""Dev Cockpitの設定、Git worktree、Agent Job管理。"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


MAX_PROMPT_LENGTH = 20_000
MAX_COMMIT_MESSAGE_LENGTH = 200


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bounded_text(value: Any, limit: int, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{field_name} is too long (max {limit} characters)")
    return value


def run_git(repository: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repository, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, check=False,
    )


def ensure_git_repository(repository: Path) -> None:
    result = run_git(repository, ["rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        raise ValueError(f"not a Git repository: {repository}")


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    repository: Path


@dataclass
class Job:
    id: str
    project_id: str
    agent: str
    prompt: str
    status: str = "queued"
    branch: str = ""
    worktree: str = ""
    parent_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error: str | None = None
    log: list[str] = field(default_factory=list)
    changed_files: list[dict[str, Any]] = field(default_factory=list)
    diff_stat: str = ""
    routed_agent: str | None = None
    route_source: str | None = None
    route_confidence: float | None = None
    route_reasons: list[str] = field(default_factory=list)
    route_scores: dict[str, float] = field(default_factory=dict)

    def public(self, include_log: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if not include_log:
            data["log"] = self.log[-40:]
        return data


class JobManager:
    """Jobを専用worktreeで実行し、レビュー可能な状態を保持する。"""

    def __init__(self, projects: Iterable[Project], agents: dict[str, list[str]], jobs_root: Path, on_change: Callable[[], None] | None = None, router: Any | None = None) -> None:
        self.projects = {project.id: project for project in projects}
        self.agents = agents
        self.jobs_root = jobs_root
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.on_change = on_change
        self.router = router
        self._jobs: dict[str, Job] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()
        self._load_jobs()

    def _load_jobs(self) -> None:
        for path in self.jobs_root.glob("*/job.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self._jobs[raw["id"]] = Job(**raw)
            except (OSError, ValueError, TypeError, KeyError):
                # 壊れた履歴1件でサーバー全体を起動不能にしない。
                continue

    def _persist(self, job: Job) -> None:
        directory = self.jobs_root / job.id
        directory.mkdir(parents=True, exist_ok=True)
        temp_path = directory / "job.json.tmp"
        temp_path.write_text(json.dumps(asdict(job), ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(directory / "job.json")
        if self.on_change:
            self.on_change()

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)

    def get(self, job_id: str) -> Job:
        with self._lock:
            try:
                return self._jobs[job_id]
            except KeyError as exc:
                raise KeyError(f"unknown job: {job_id}") from exc

    def available_agents(self) -> list[str]:
        names = list(self.agents)
        if self.router is not None:
            return [self.router.auto_agent, *names]
        return names

    def create(self, project_id: str, agent: str, prompt: str, parent_id: str | None = None) -> Job:
        prompt = bounded_text(prompt, MAX_PROMPT_LENGTH, "prompt")
        if project_id not in self.projects:
            raise ValueError("unknown project")
        is_auto = self.router is not None and agent == self.router.auto_agent
        if agent not in self.agents and not is_auto:
            raise ValueError("unknown agent")
        if parent_id and self.get(parent_id).status == "running":
            raise ValueError("the parent job is still running")
        job = Job(id=uuid.uuid4().hex[:12], project_id=project_id, agent=agent, prompt=prompt, parent_id=parent_id)
        with self._lock:
            self._jobs[job.id] = job
            self._persist(job)
        threading.Thread(target=self._run, args=(job.id,), daemon=True).start()
        return job

    def _append_log(self, job: Job, line: str) -> None:
        line = line.rstrip("\r\n")
        if not line:
            return
        with self._lock:
            job.log.append(line)
            if len(job.log) > 2_000:
                del job.log[:-2_000]
            self._persist(job)

    def _render_command(self, job: Job) -> list[str]:
        selected_agent = job.routed_agent or job.agent
        if selected_agent not in self.agents:
            raise ValueError("job has no executable agent")
        return [part.format(prompt=job.prompt, worktree=job.worktree, project=job.project_id, job_id=job.id) for part in self.agents[selected_agent]]

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            project = self.projects[job.project_id]
            job.status, job.started_at = "running", utc_now()
            parent = self._jobs.get(job.parent_id) if job.parent_id else None
            if parent:
                job.branch = parent.branch
                worktree = Path(parent.worktree)
            else:
                job.branch = f"cockpit/{job.id}"
                worktree = self.jobs_root / job.id / "worktree"
            job.worktree = str(worktree)
            self._persist(job)
        try:
            ensure_git_repository(project.repository)
            if self.router is not None and job.agent == self.router.auto_agent:
                decision = self.router.route(job.prompt)
                if decision.agent not in self.agents:
                    raise RuntimeError("router selected an unknown agent")
                with self._lock:
                    job.routed_agent = decision.agent
                    job.route_source = decision.source
                    job.route_confidence = decision.confidence
                    job.route_reasons = list(decision.reasons)
                    job.route_scores = dict(decision.scores)
                    self._persist(job)
                confidence = "" if decision.confidence is None else f" confidence={decision.confidence:.2f}"
                self._append_log(job, f"[router] {decision.source} -> {decision.agent}{confidence}")
                if decision.reasons:
                    self._append_log(job, f"[router] reasons: {', '.join(decision.reasons)}")
            if parent:
                if not worktree.is_dir():
                    raise RuntimeError("parent worktree no longer exists")
            else:
                worktree.parent.mkdir(parents=True, exist_ok=True)
                result = run_git(project.repository, ["worktree", "add", "-b", job.branch, str(worktree), "HEAD"], timeout=60)
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or "git worktree add failed")
            command = self._render_command(job)
            self._append_log(job, f"$ {self._display_command(command)}")
            process = subprocess.Popen(command, cwd=worktree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
            with self._lock:
                self._processes[job.id] = process
            assert process.stdout is not None
            for line in process.stdout:
                self._append_log(job, line)
            process.wait()
            with self._lock:
                job.exit_code = process.returncode
                if job.status != "stopped":
                    job.status = "completed" if process.returncode == 0 else "failed"
            self._refresh_diff(job)
        except Exception as exc:  # noqa: BLE001 - Jobをfailedとして記録する境界。
            with self._lock:
                job.status, job.error = "failed", str(exc)
            self._append_log(job, f"ERROR: {exc}")
        finally:
            with self._lock:
                self._processes.pop(job.id, None)
                job.finished_at = utc_now()
                self._persist(job)

    @staticmethod
    def _display_command(command: list[str]) -> str:
        return " ".join(arg if " " not in arg else repr(arg) for arg in command)

    def _refresh_diff(self, job: Job) -> None:
        if not job.worktree or not Path(job.worktree).is_dir():
            return
        worktree = Path(job.worktree)
        stat = run_git(worktree, ["diff", "--stat", "HEAD"])
        names = run_git(worktree, ["diff", "--name-status", "HEAD"])
        with self._lock:
            job.diff_stat = stat.stdout.strip()
            job.changed_files = []
            for line in names.stdout.splitlines():
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    job.changed_files.append({"status": parts[0], "path": parts[1]})
            self._persist(job)

    def stop(self, job_id: str) -> Job:
        with self._lock:
            job = self.get(job_id)
            process = self._processes.get(job_id)
            if job.status != "running" or process is None:
                raise ValueError("job is not running")
            job.status, job.error = "stopped", "stopped by user"
            self._persist(job)
        if os.name == "nt":
            process.terminate()
        else:
            process.send_signal(signal.SIGTERM)
        return job

    def diff(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        self._refresh_diff(job)
        if not job.worktree or not Path(job.worktree).is_dir():
            return {"stat": "", "files": [], "patch": ""}
        result = run_git(Path(job.worktree), ["diff", "--no-ext-diff", "HEAD"], timeout=60)
        return {"stat": job.diff_stat, "files": job.changed_files, "patch": result.stdout}

    def read_file(self, job_id: str, relative_path: str) -> str:
        job = self.get(job_id)
        if not job.worktree:
            raise ValueError("job has no worktree")
        root, target = Path(job.worktree).resolve(), (Path(job.worktree) / relative_path).resolve()
        if target != root and root not in target.parents:
            raise ValueError("path escapes worktree")
        if not target.is_file():
            raise FileNotFoundError(relative_path)
        if target.stat().st_size > 2_000_000:
            raise ValueError("file is too large")
        return target.read_text(encoding="utf-8", errors="replace")

    def approve(self, job_id: str, commit_message: str) -> Job:
        job = self.get(job_id)
        commit_message = bounded_text(commit_message, MAX_COMMIT_MESSAGE_LENGTH, "commitMessage")
        if job.status not in {"completed", "failed", "stopped"}:
            raise ValueError("job must be finished before approval")
        result = run_git(Path(job.worktree), ["add", "--all"], timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "git add failed")
        result = run_git(Path(job.worktree), ["commit", "-m", commit_message], timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "git commit failed")
        self._append_log(job, f"Committed: {commit_message}")
        self._refresh_diff(job)
        return job

    def push(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status not in {"completed", "failed", "stopped"}:
            raise ValueError("job must be finished before push")
        result = run_git(Path(job.worktree), ["push", "--set-upstream", "origin", job.branch], timeout=120)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "git push failed")
        self._append_log(job, f"Pushed branch: {job.branch}")
        return job

    def discard(self, job_id: str) -> None:
        job = self.get(job_id)
        if job.status == "running":
            raise ValueError("stop the running job before discarding it")
        project, worktree = self.projects[job.project_id], Path(job.worktree)
        if not job.parent_id and worktree.is_dir():
            result = run_git(project.repository, ["worktree", "remove", "--force", str(worktree)], timeout=60)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "git worktree remove failed")
        shutil.rmtree(self.jobs_root / job.id, ignore_errors=False)
        with self._lock:
            self._jobs.pop(job.id, None)
