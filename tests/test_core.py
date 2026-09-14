import tempfile
import unittest
from pathlib import Path

from cockpit.core import Job, JobManager, Project, bounded_text


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


if __name__ == "__main__":
    unittest.main()
