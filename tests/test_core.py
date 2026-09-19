import tempfile
import unittest
from pathlib import Path

from cockpit.core import Job, JobManager, Project, bounded_text
from cockpit.router import RouteDecision


class FakeRouter:
    auto_agent = "auto"

    def route(self, prompt):
        return RouteDecision(agent="devin-swe2", source="test", confidence=0.9)


class CoreTests(unittest.TestCase):
    def test_bounded_text_rejects_empty_and_large_values(self):
        with self.assertRaises(ValueError):
            bounded_text("  ", 10, "prompt")
        with self.assertRaises(ValueError):
            bounded_text("x" * 11, 10, "prompt")

    def test_job_manager_rejects_unknown_project_and_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = JobManager([], {}, Path(directory))
            with self.assertRaises(ValueError):
                manager.create("missing", "codex", "hello")

    def test_job_persistence_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = JobManager([Project("demo", "Demo", root)], {"codex": ["echo", "{prompt}"]}, root / "jobs")
            job = Job(id="abc123", project_id="demo", agent="codex", prompt="hello")
            manager._jobs[job.id] = job
            manager._persist(job)
            reloaded = JobManager([Project("demo", "Demo", root)], {"codex": ["echo", "{prompt}"]}, root / "jobs")
            self.assertEqual(reloaded.get("abc123").prompt, "hello")

    def test_route_metadata_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = JobManager([Project("demo", "Demo", root)], {"codex": ["echo", "{prompt}"]}, root / "jobs")
            job = Job(id="route123", project_id="demo", agent="auto", prompt="hello", routed_agent="codex", route_source="jev", route_confidence=0.8)
            manager._jobs[job.id] = job
            manager._persist(job)
            restored = JobManager([Project("demo", "Demo", root)], {"codex": ["echo", "{prompt}"]}, root / "jobs").get(job.id)
            self.assertEqual(restored.routed_agent, "codex")
            self.assertEqual(restored.route_source, "jev")
            self.assertEqual(restored.route_confidence, 0.8)

    def test_auto_agent_and_routed_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = JobManager(
                [Project("demo", "Demo", root)],
                {"devin-swe2": ["echo", "{prompt}"]},
                root / "jobs",
                router=FakeRouter(),
            )
            self.assertEqual(manager.available_agents(), ["auto", "devin-swe2"])
            job = Job(id="route123", project_id="demo", agent="auto", prompt="hello", worktree=str(root), routed_agent="devin-swe2")
            self.assertEqual(manager._render_command(job), ["echo", "hello"])


if __name__ == "__main__":
    unittest.main()
