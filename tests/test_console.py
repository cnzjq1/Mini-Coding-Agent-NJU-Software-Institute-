import io
import unittest
from contextlib import redirect_stdout

from coding_agent.console import ConsoleReporter


class ConsoleReporterTests(unittest.TestCase):
    def test_step_displays_relevant_tool_argument(self):
        output = io.StringIO()
        with redirect_stdout(output):
            reporter = ConsoleReporter(True)
            reporter.step(2, 30, "run_command", '{"command":"python -m unittest"}')
            reporter.step(3, 30, "write_file", '{"path":"src/app.py","content":"..."}')

        text = output.getvalue()
        self.assertIn("run_command  python -m unittest", text)
        self.assertIn("write_file  src/app.py", text)

    def test_methodology_omits_branch_working(self):
        status = {
            "criteria_verified": 1,
            "criteria_total": 2,
            "adversarial_completed": False,
            "decisions": 1,
            "assumption_budget_used": 1,
            "assumption_budget_limit": 3,
            "high_risk_assumptions_open": [],
            "branch_goal_achieved": False,
        }
        output = io.StringIO()
        with redirect_stdout(output):
            ConsoleReporter(True).methodology(status)

        self.assertNotIn("branch", output.getvalue())
        self.assertNotIn("working", output.getvalue())


if __name__ == "__main__":
    unittest.main()
