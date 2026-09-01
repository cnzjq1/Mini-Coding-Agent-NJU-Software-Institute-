import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from coding_agent.tools import LocalTools
from coding_agent.session import SessionStore


class LocalToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tools = LocalTools(self.root, timeout=5)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, name, **kwargs):
        return json.loads(self.tools.execute(name, kwargs))

    def test_write_read_replace_and_list(self):
        self.assertTrue(self.call("write_file", path="src/a.txt", content="hello")["ok"])
        self.assertEqual(self.call("read_file", path="src/a.txt")["content"], "hello")
        self.assertTrue(self.call("replace_in_file", path="src/a.txt", old="hello", new="world")["ok"])
        self.assertIn("src/a.txt", self.call("list_files", recursive=True)["entries"])

    def test_path_escape_is_rejected(self):
        result = self.call("write_file", path="../escape.txt", content="bad")
        self.assertFalse(result["ok"])
        self.assertIn("escapes", result["error"])

    def test_command_result(self):
        result = self.call("run_command", command="python -c \"print('ok')\"")
        self.assertTrue(result["ok"])
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"].strip(), "ok")

    def test_session_metadata_is_protected(self):
        result = self.call("write_file", path=".mini_coding_agent/session.json", content="bad")
        self.assertFalse(result["ok"])
        self.assertIn("protected", result["error"])

    def test_finish_requires_validation_and_existing_entrypoint(self):
        self.call("write_file", path="app.py", content="print('ok')")
        rejected = self.call(
            "finish_project", summary="done", run_command="python app.py", entrypoints=["app.py"]
        )
        self.assertFalse(rejected["ok"])
        self.call("set_acceptance_criteria", criteria=[{
            "id": "AC-1", "description": "app runs", "verification": "python app.py"
        }])
        self.call("run_command", command="python app.py")
        self.call("record_evidence", criterion_id="AC-1", note="passed")
        self.call("record_adversarial_check", cases=["repeat"], findings="none")
        accepted = self.call(
            "finish_project", summary="done", run_command="python app.py", entrypoints=["app.py"]
        )
        self.assertTrue(accepted["accepted"])

    def test_output_is_truncated(self):
        tools = LocalTools(self.root, max_output_chars=20)
        self.assertTrue(json.loads(tools.execute("write_file", {"path": "long.txt", "content": "x" * 100}))["ok"])
        read = json.loads(tools.execute("read_file", {"path": "long.txt"}))
        self.assertIn("truncated", read["content"])

    def test_atomic_write_failure_preserves_old_file(self):
        target = self.root / "safe.txt"
        target.write_text("old", encoding="utf-8")
        with patch("coding_agent.tools.os.replace", side_effect=OSError("replace failed")):
            result = self.call("write_file", path="safe.txt", content="new")
        self.assertFalse(result["ok"])
        self.assertEqual(target.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(self.root.glob(".safe.txt.*.tmp")), [])

    def test_finish_allows_display_test_command_to_differ(self):
        self.call("write_file", path="app.py", content="print('ok')")
        self.call("run_command", command="python app.py")
        self.call("set_acceptance_criteria", criteria=[{
            "id": "AC-1", "description": "runs", "verification": "run the program"
        }])
        self.call("record_evidence", criterion_id="AC-1", note="passed")
        self.call("record_adversarial_check", cases=["repeat"], findings="passed")
        result = self.call(
            "finish_project", summary="done", run_command="python app.py",
            entrypoints=["app.py"], test_command="python -m unittest",
        )
        self.assertTrue(result["accepted"])

    def test_repeated_command_failure_returns_memory_signature(self):
        command = "python -c \"import sys; print('same failure', file=sys.stderr); sys.exit(1)\""
        first = self.call("run_command", command=command)
        second = self.call("run_command", command=command)
        self.assertEqual(first["failure_signature"], second["failure_signature"])
        self.assertEqual(second["failure_count"], 2)
        self.assertIn("Repeated failure", second["guidance"])

    def test_evidence_automatically_binds_latest_successful_command(self):
        self.call("set_acceptance_criteria", criteria=[{
            "id": "AC-1", "description": "real tests", "verification": "python -m unittest"
        }])
        self.call("run_command", command="python -c \"print('unrelated')\"")
        result = self.call(
            "record_evidence", criterion_id="AC-1",
            note="successful smoke check",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["evidence"]["command"], "python -c \"print('unrelated')\""
        )

    def test_branch_decisions_are_on_demand_and_lock_after_goal(self):
        session = SessionStore(self.root)
        root = session.add({"role": "user", "content": "root"})
        other = session.add({"role": "tool", "content": "other decision"})
        session.record_experiment(other, {
            "id": "DEC-OTHER", "question": "storage", "selected": "sqlite",
            "alternatives": [{"name": "sqlite", "score": 9}], "rationale": "safe",
        })
        session.checkout(root)
        session.add({"role": "user", "content": "current branch"})
        self.tools.attach_session(session)
        available = self.call("inspect_other_branch_decisions")
        self.assertEqual(available["decisions"][0]["id"], "DEC-OTHER")
        self.call(
            "set_acceptance_criteria",
            criteria=[{"id": "AC-1", "description": "goal", "verification": "smoke"}],
        )
        self.call("run_command", command="python -c \"print('ok')\"")
        self.call("record_evidence", criterion_id="AC-1", note="passed")
        self.call("record_adversarial_check", cases=["repeat"], findings="passed")
        self.assertTrue(self.tools.methodology.status()["objective_satisfied"])
        locked = self.call("inspect_other_branch_decisions")
        self.assertFalse(locked["ok"])
        self.assertIn("task is complete", locked["error"])
        rejected = self.call(
            "decide_branch_strategy", goal_achieved=False, action="switch",
            reason="unnecessary", decision_id="DEC-OTHER",
        )
        self.assertFalse(rejected["ok"])

        mutation = self.call("write_file", path="late.txt", content="too late")
        self.assertFalse(mutation["ok"])
        self.assertFalse((self.root / "late.txt").exists())


if __name__ == "__main__":
    unittest.main()
