import tempfile
import unittest
from pathlib import Path

from coding_agent.methodology import CheckpointManager, FailureMemory, MethodologyStore


class MethodologyTests(unittest.TestCase):
    def test_acceptance_evidence_assumptions_decision_and_adversarial_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            store = MethodologyStore(Path(folder))
            store.set_criteria([{"id": "AC-1", "description": "works", "verification": "test"}])
            store.add_assumption("A-1", "database may be remote", "high", True)
            store.add_decision(
                "storage", [
                    {"name": "sqlite", "pros": ["small"], "cons": ["local"], "score": 8},
                    {"name": "json", "pros": ["simple"], "cons": ["locking"], "score": 5},
                ], "sqlite", "higher reliability",
            )
            store.add_evidence("AC-1", "passed", ["test"])
            store.record_adversarial(["empty input"], "passed", ["test"])
            with self.assertRaisesRegex(ValueError, "high-risk"):
                store.require_finish_ready()
            store.resolve_assumption("A-1", "user requirement confirms local database")
            store.branch_strategy(True, "continue", "all acceptance and edge tests passed")
            store.require_finish_ready()
            status = store.status()
            self.assertEqual(status["criteria_verified"], 1)
            self.assertEqual(status["decisions"], 1)

    def test_failure_memory_detects_repetition(self):
        with tempfile.TemporaryDirectory() as folder:
            memory = FailureMemory(Path(folder))
            first = memory.record("pytest", "File C:\\tmp\\a.py, line 12: AssertionError")
            second = memory.record("pytest", "File C:\\tmp\\b.py, line 99: AssertionError")
            self.assertEqual(first["signature"], second["signature"])
            self.assertEqual(second["count"], 2)

    def test_medium_risk_assumption_budget_is_enforced(self):
        with tempfile.TemporaryDirectory() as folder:
            store = MethodologyStore(Path(folder))
            store.set_criteria([{"id": "AC", "description": "ok", "verification": "test"}])
            store.add_evidence("AC", "ok", ["test"])
            store.record_adversarial(["edge"], "ok", ["test"])
            store.branch_strategy(True, "continue", "checks passed")
            for index in range(4):
                store.add_assumption(f"M-{index}", "uncertain detail", "medium", True)
            with self.assertRaisesRegex(ValueError, "Too many"):
                store.require_finish_ready()

    def test_goal_achieved_locks_switching_and_switch_resets_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            store = MethodologyStore(Path(folder))
            store.set_criteria([{"id": "AC", "description": "ok", "verification": "test"}])
            switched = store.branch_strategy(False, "switch", "current design is blocked", alternative="new design")
            self.assertEqual(switched["action"], "switch")
            self.assertEqual(store.status()["criteria_pending"], ["AC"])
            store.add_evidence("AC", "ok", ["test"])
            store.record_adversarial(["edge"], "ok", ["test"])
            with self.assertRaisesRegex(ValueError, "objectively"):
                store.branch_strategy(False, "switch", "unnecessary", alternative="another design")
            store.branch_strategy(True, "continue", "new design reached the goal")
            with self.assertRaisesRegex(ValueError, "objectively|locked"):
                store.branch_strategy(False, "switch", "try again", alternative="third design")

    def test_checkpoint_rolls_back_created_and_modified_files_after_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            existing = root / "existing.txt"
            created = root / "created.txt"
            existing.write_text("old", encoding="utf-8")
            manager = CheckpointManager(root)
            manager.before_mutation(existing)
            manager.before_mutation(created)
            existing.write_text("new", encoding="utf-8")
            created.write_text("created", encoding="utf-8")
            reloaded = CheckpointManager(root)
            result = reloaded.rollback("validation regressed")
            self.assertEqual(result["restored"], 2)
            self.assertEqual(existing.read_text(encoding="utf-8"), "old")
            self.assertFalse(created.exists())


if __name__ == "__main__":
    unittest.main()
