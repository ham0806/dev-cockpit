"""Jevを前段に置くAgentルーター。"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class RouteDecision:
    agent: str
    source: str
    confidence: float | None = None
    reasons: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    probabilities: dict[str, float] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return asdict(self)


class TaskRouter:
    def __init__(
        self,
        agents: Iterable[str],
        *,
        targets: dict[str, str],
        fallback_agent: str,
        evaluator_command: list[str] | None = None,
        auto_agent: str = "auto",
        history_file: Path | None = None,
        cwd: Path | None = None,
        timeout_seconds: float = 10.0,
        min_confidence: float = 0.55,
        astra_agent: str | None = "codex-astra",
        astra_fallback_agent: str | None = "codex-sol",
        astra_min_score: float = 2.4,
    ) -> None:
        self.agents = set(agents)
        self.targets = dict(targets)
        self.fallback_agent = fallback_agent
        self.evaluator_command = list(evaluator_command or [])
        self.auto_agent = auto_agent
        self.history_file = history_file
        self.cwd = cwd
        self.timeout_seconds = timeout_seconds
        self.min_confidence = min_confidence
        self.astra_agent = astra_agent
        self.astra_fallback_agent = astra_fallback_agent
        self.astra_min_score = astra_min_score

        if not self.agents:
            raise ValueError("router requires at least one agent")
        if auto_agent in self.agents:
            raise ValueError("routing.auto_agent must not collide with an agent")
        if fallback_agent not in self.agents:
            raise ValueError("routing.fallback_agent must reference an agent")
        if not self.targets or set(self.targets) - self.agents:
            raise ValueError("routing.targets contains unknown agents")
        if astra_agent and astra_agent not in self.agents:
            raise ValueError("routing.astra_agent must reference an agent")
        if astra_fallback_agent and astra_fallback_agent not in self.agents:
            raise ValueError("routing.astra_fallback_agent must reference an agent")
        if timeout_seconds <= 0:
            raise ValueError("routing.timeout_seconds must be positive")
        if not 0 <= min_confidence <= 1:
            raise ValueError("routing.min_confidence must be between 0 and 1")
        if not 0 <= astra_min_score <= 3:
            raise ValueError("routing.astra_min_score must be between 0 and 3")

    def route(self, prompt: str) -> RouteDecision:
        try:
            decision = self._from_payload(self._evaluate(prompt))
        except (OSError, subprocess.SubprocessError, ValueError):
            decision = self._heuristic(prompt)
        decision = self._apply_policy(decision)
        self._record(prompt, decision)
        return decision

    def _evaluate(self, prompt: str) -> dict[str, Any]:
        if not self.evaluator_command:
            raise ValueError("routing evaluator is not configured")
        result = subprocess.run(
            self.evaluator_command,
            input=json.dumps({"prompt": prompt, "targets": self.targets}, ensure_ascii=False),
            cwd=self.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            raise subprocess.SubprocessError("routing evaluator failed")
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            raise ValueError("routing evaluator returned no output")
        payload = json.loads(lines[-1])
        if not isinstance(payload, dict):
            raise ValueError("routing evaluator output must be an object")
        return payload

    @staticmethod
    def _numbers(value: Any, low: float | None = None, high: float | None = None) -> dict[str, float]:
        if not isinstance(value, dict):
            return {}
        output: dict[str, float] = {}
        for key, raw in value.items():
            if isinstance(key, str) and isinstance(raw, (int, float)) and not isinstance(raw, bool):
                number = float(raw)
                if low is not None:
                    number = max(low, number)
                if high is not None:
                    number = min(high, number)
                output[key] = number
        return output

    def _from_payload(self, raw: dict[str, Any]) -> RouteDecision:
        agent = raw.get("agent")
        if not isinstance(agent, str) or agent not in self.targets:
            raise ValueError("routing evaluator selected an unknown agent")
        confidence = raw.get("confidence")
        confidence = float(confidence) if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None
        if confidence is not None:
            confidence = max(0.0, min(1.0, confidence))
        return RouteDecision(
            agent=agent,
            source="jev",
            confidence=confidence,
            reasons=["jev_choice"],
            scores=self._numbers(raw.get("scores"), 0.0, 3.0),
            probabilities=self._numbers(raw.get("probabilities"), 0.0, 1.0),
        )

    def _apply_policy(self, decision: RouteDecision) -> RouteDecision:
        if decision.confidence is not None and decision.confidence < self.min_confidence and decision.agent != self.fallback_agent:
            decision = replace(decision, agent=self.fallback_agent, reasons=[*decision.reasons, "low_confidence_fallback"])
        if self.astra_agent and decision.agent == self.astra_agent:
            risk = max(
                decision.scores.get("architecture_impact", 0.0),
                decision.scores.get("ambiguity", 0.0),
                decision.scores.get("blast_radius", 0.0),
            )
            if risk < self.astra_min_score:
                decision = replace(
                    decision,
                    agent=self.astra_fallback_agent or self.fallback_agent,
                    reasons=[*decision.reasons, "astra_threshold_downgrade"],
                )
        return decision

    def _heuristic(self, prompt: str) -> RouteDecision:
        text = prompt.casefold()
        light = ("readme", "typo", "lint", "format", "rename", "コメント", "誤字", "文言", "整形")
        strong = (
            "architecture", "migration", "schema", "database", "deadlock", "race condition", "security",
            "authentication", "authorization", "performance", "large refactor", "設計", "移行", "スキーマ",
            "データベース", "db", "デッドロック", "競合", "セキュリティ", "認証", "認可", "性能", "障害",
            "大規模", "リファクタ",
        )
        if any(term in text for term in strong) and "codex-sol" in self.agents:
            agent, reason = "codex-sol", "heuristic_complex_task"
            scores = {"complexity": 2.0, "architecture_impact": 1.5, "blast_radius": 1.5, "ambiguity": 1.0}
        elif any(term in text for term in light) and "codex-luna" in self.agents:
            agent, reason = "codex-luna", "heuristic_light_task"
            scores = {"complexity": 0.5, "architecture_impact": 0.0, "blast_radius": 0.5, "ambiguity": 0.5}
        else:
            agent, reason = self.fallback_agent, "heuristic_default_fallback"
            scores = {"complexity": 1.0, "architecture_impact": 0.5, "blast_radius": 0.5, "ambiguity": 0.5}
        return RouteDecision(agent=agent, source="heuristic", reasons=["evaluator_unavailable", reason], scores=scores)

    def _record(self, prompt: str, decision: RouteDecision) -> None:
        self._append_history({
            "event": "decision",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_length": len(prompt),
            **decision.public(),
        })

    def record_outcome(self, prompt: str, agent: str, status: str, exit_code: int | None) -> None:
        self._append_history({
            "event": "outcome",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_length": len(prompt),
            "agent": agent,
            "status": status,
            "exit_code": exit_code,
        })

    def _append_history(self, record: dict[str, Any]) -> None:
        if self.history_file is None:
            return
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with self.history_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            return
