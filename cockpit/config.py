"""Dev Cockpitの設定読み込みと入力検証。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import Project, ensure_git_repository


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
