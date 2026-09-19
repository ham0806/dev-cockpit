"""Dev Cockpitの設定読み込みと入力検証。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import Project, ensure_git_repository
from .router import TaskRouter


def load_config(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config must be a JSON object")
    if not isinstance(raw.get("projects"), list) or not raw["projects"]:
        raise ValueError("config.projects must contain at least one project")
    if not isinstance(raw.get("agents"), dict) or not raw["agents"]:
        raise ValueError("config.agents must contain at least one agent")
    return raw


def make_projects(raw: dict[str, Any]) -> list[Project]:
    projects: list[Project] = []
    seen: set[str] = set()
    for item in raw["projects"]:
        if not isinstance(item, dict):
            raise ValueError("each project must be an object")
        project_id, name, repository = item.get("id"), item.get("name", item.get("id")), item.get("repository")
        if not isinstance(project_id, str) or not project_id or project_id in seen:
            raise ValueError("project ids must be unique non-empty strings")
        if not isinstance(name, str) or not isinstance(repository, str):
            raise ValueError(f"invalid project: {project_id}")
        path = Path(repository).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"project directory does not exist: {path}")
        ensure_git_repository(path)
        seen.add(project_id)
        projects.append(Project(id=project_id, name=name, repository=path))
    return projects


def make_agents(raw: dict[str, Any]) -> dict[str, list[str]]:
    agents: dict[str, list[str]] = {}
    for name, command in raw["agents"].items():
        if not isinstance(name, str) or not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError(f"invalid agent command: {name}")
        agents[name] = command
    return agents


def make_router(raw: dict[str, Any], agents: dict[str, list[str]], config_dir: Path) -> TaskRouter | None:
    routing = raw.get("routing")
    if routing is None:
        return None
    if not isinstance(routing, dict):
        raise ValueError("config.routing must be an object")
    if not routing.get("enabled", False):
        return None

    auto_agent = routing.get("auto_agent", "auto")
    fallback_agent = routing.get("fallback_agent")
    targets = routing.get("targets")
    evaluator_command = routing.get("evaluator_command", [])
    if not isinstance(auto_agent, str) or not auto_agent:
        raise ValueError("routing.auto_agent must be a non-empty string")
    if not isinstance(fallback_agent, str) or not fallback_agent:
        raise ValueError("routing.fallback_agent must be a non-empty string")
    if not isinstance(targets, dict) or not targets or not all(
        isinstance(key, str) and key and isinstance(value, str) and value
        for key, value in targets.items()
    ):
        raise ValueError("routing.targets must map agent names to descriptions")
    if not isinstance(evaluator_command, list) or not all(
        isinstance(part, str) and part for part in evaluator_command
    ):
        raise ValueError("routing.evaluator_command must be a list of strings")

    history_value = routing.get("history_file", "runtime/router.jsonl")
    if not isinstance(history_value, str) or not history_value:
        raise ValueError("routing.history_file must be a non-empty string")
    history_file = Path(history_value).expanduser()
    if not history_file.is_absolute():
        history_file = (config_dir / history_file).resolve()

    return TaskRouter(
        agents=agents,
        targets=targets,
        fallback_agent=fallback_agent,
        evaluator_command=evaluator_command,
        auto_agent=auto_agent,
        history_file=history_file,
        cwd=config_dir.resolve(),
        timeout_seconds=float(routing.get("timeout_seconds", 10)),
        min_confidence=float(routing.get("min_confidence", 0.55)),
        astra_agent=routing.get("astra_agent", "codex-astra"),
        astra_fallback_agent=routing.get("astra_fallback_agent", "codex-sol"),
        astra_min_score=float(routing.get("astra_min_score", 2.4)),
    )
