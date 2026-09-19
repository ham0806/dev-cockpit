import json
import tempfile
import unittest
from pathlib import Path

from cockpit.router import TaskRouter


AGENTS = {"devin-swe2", "codex-luna", "codex-sol", "codex-astra"}
TARGETS = {name: name for name in AGENTS}


class StubRouter(TaskRouter):
    def __init__(self, payload, **kwargs):
        self.payload = payload
        super().__init__(**kwargs)

    def _evaluate(self, prompt):
        return self.payload


class RouterTests(unittest.TestCase):
    def make_router(self, **overrides):
        params = dict(
            agents=AGENTS,
            targets=TARGETS,
            fallback_agent="devin-swe2",
            evaluator_command=[],
            astra_agent="codex-astra",
            astra_fallback_agent="codex-sol",
        )
        params.update(overrides)
        return TaskRouter(**params)

    def test_heuristic_defaults_to_devin(self):
        decision = self.make_router().route("Add a validation check and tests")
        self.assertEqual(decision.agent, "devin-swe2")
        self.assertEqual(decision.source, "heuristic")

    def test_heuristic_uses_luna_for_light_work(self):
        self.assertEqual(self.make_router().route("READMEの誤字を直して").agent, "codex-luna")

    def test_heuristic_uses_sol_for_complex_work(self):
        self.assertEqual(self.make_router().route("DB migrationの設計と障害時の切り戻しを考えて").agent, "codex-sol")

    def test_low_confidence_falls_back_to_devin(self):
        router = StubRouter(
            {"agent": "codex-sol", "confidence": 0.2, "scores": {}},
            agents=AGENTS, targets=TARGETS, fallback_agent="devin-swe2",
            astra_agent="codex-astra", astra_fallback_agent="codex-sol",
        )
        decision = router.route("anything")
        self.assertEqual(decision.agent, "devin-swe2")
        self.assertIn("low_confidence_fallback", decision.reasons)

    def test_astra_is_guarded_by_risk_score(self):
        low = StubRouter(
            {"agent": "codex-astra", "confidence": 0.95, "scores": {"architecture_impact": 1, "ambiguity": 1, "blast_radius": 1.5}},
            agents=AGENTS, targets=TARGETS, fallback_agent="devin-swe2",
            astra_agent="codex-astra", astra_fallback_agent="codex-sol", astra_min_score=2.4,
        ).route("anything")
        high = StubRouter(
            {"agent": "codex-astra", "confidence": 0.95, "scores": {"architecture_impact": 2.7, "ambiguity": 1, "blast_radius": 2.8}},
            agents=AGENTS, targets=TARGETS, fallback_agent="devin-swe2",
            astra_agent="codex-astra", astra_fallback_agent="codex-sol", astra_min_score=2.4,
        ).route("anything")
        self.assertEqual(low.agent, "codex-sol")
        self.assertIn("astra_threshold_downgrade", low.reasons)
        self.assertEqual(high.agent, "codex-astra")

    def test_history_stores_hash_not_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory) / "router.jsonl"
            prompt = "secret project prompt"
            self.make_router(history_file=history).route(prompt)
            raw = history.read_text(encoding="utf-8")
            record = json.loads(raw.strip())
            self.assertNotIn(prompt, raw)
            self.assertEqual(record["prompt_length"], len(prompt))
            self.assertEqual(len(record["prompt_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
