"""Completion and decision recovery; all files live in the runner's temporary directory."""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode = True
SOURCE = Path(sys.argv.pop(1)).resolve()
TEMP_ROOT = sys.argv.pop(1)
spec = importlib.util.spec_from_file_location("status", SOURCE)
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)


class RecoveryTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_cli("init", "--local")
        self.run_cli("claim", "first task")
        self.run_cli("claim", "second task")
        self.path = self.root / status.STATUS
        self.original = self.path.read_text()
        self.pending = self.root / status.STATE / status.DONE_PENDING
        self.log = self.root / status.STATE / "log" / f"{status.today()[:7]}.md"
        self.command = "done"
        self.args = SimpleNamespace(what=["1"])

    def run_cli(self, *args):
        result = subprocess.run([sys.executable, str(SOURCE), *args], cwd=self.root,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def fail_write(self, target, after=False):
        original_write = status.write

        def write(path, text):
            if path == target:
                if after:
                    original_write(path, text)
                raise OSError("simulated interrupted write")
            original_write(path, text)

        with patch.object(status, "write", side_effect=write), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                getattr(status, f"cmd_{self.command}")(self.root, self.args)


class DoneRecoveryTests(RecoveryTestCase):
    def assert_completed_once(self):
        self.assertEqual(status.items(self.path.read_text().splitlines(), "Now"), ["second task"])
        self.assertEqual(self.log.read_text().splitlines().count("- first task"), 1)
        self.assertFalse(self.pending.exists())

    def test_pending_write_failure_changes_neither_file(self):
        self.fail_write(self.pending)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.pending.exists())

    def test_interrupt_after_pending_save_can_retry(self):
        self.fail_write(self.pending, after=True)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertFalse(self.log.exists())
        self.run_cli("done", "1")
        self.assert_completed_once()

    def test_log_write_failure_keeps_now_and_can_retry(self):
        self.fail_write(self.log)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertFalse(self.log.exists())
        self.assertTrue(self.pending.exists())
        self.run_cli("done", "1")
        self.assert_completed_once()

    def test_interrupt_after_log_save_does_not_duplicate_entry(self):
        self.fail_write(self.log, after=True)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertIn("- first task", self.log.read_text())
        self.run_cli("done", "1")
        self.assert_completed_once()

    def test_status_write_failure_keeps_log_and_can_retry(self):
        self.fail_write(self.path)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertIn("- first task", self.log.read_text())
        self.run_cli("done", "1")
        self.assert_completed_once()

    def test_interrupt_after_status_save_does_not_finish_next_item(self):
        self.fail_write(self.path, after=True)
        self.assertNotIn("- [ ] first task", self.path.read_text())
        self.assertTrue(self.pending.exists())
        self.run_cli("done", "1")
        self.assert_completed_once()

    def test_cleanup_failure_can_retry_without_finishing_next_item(self):
        original_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path == self.pending:
                raise OSError("simulated cleanup failure")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", unlink), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                status.cmd_done(self.root, SimpleNamespace(what=["1"]))
        self.run_cli("done", "1")
        self.assert_completed_once()

    def test_manual_status_edit_is_preserved_before_any_recovery_write(self):
        self.fail_write(self.log)
        edited = self.original.replace("## Goal\n- ", "## Goal\n- new goal")
        self.path.write_text(edited)
        result = subprocess.run([sys.executable, str(SOURCE), "done", "1"], cwd=self.root,
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preserved", result.stderr)
        self.assertEqual(self.path.read_text(), edited)
        self.assertFalse(self.log.exists())
        self.assertTrue(self.pending.exists())

    def test_manual_log_edit_is_preserved(self):
        self.fail_write(self.path)
        edited = self.log.read_text() + "- manual note\n"
        self.log.write_text(edited)
        result = subprocess.run([sys.executable, str(SOURCE), "done", "1"], cwd=self.root,
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.log.read_text(), edited)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertTrue(self.pending.exists())

    def test_other_write_recovers_before_starting_new_work(self):
        self.fail_write(self.path)
        self.run_cli("claim", "third task")
        self.assertEqual(status.items(self.path.read_text().splitlines(), "Now"),
                         ["second task", "third task"])
        self.assertEqual(self.log.read_text().splitlines().count("- first task"), 1)
        self.assertFalse(self.pending.exists())

    def test_retry_uses_original_month(self):
        self.log = self.root / status.STATE / "log" / "2020-01.md"
        with patch.object(status, "today", return_value="2020-01-31"):
            self.fail_write(self.path)
        self.run_cli("done", "1")
        self.assert_completed_once()
        self.assertIn("## 2020-01-31", self.log.read_text())
        self.assertEqual(list(self.log.parent.glob("*.md")), [self.log])

    def test_same_task_can_be_completed_again_as_new_work(self):
        self.run_cli("done", "1")
        self.run_cli("claim", "first task")
        self.run_cli("done", "first task")
        self.assertEqual(self.log.read_text().splitlines().count("- first task"), 2)
        self.assertEqual(status.items(self.path.read_text().splitlines(), "Now"), ["second task"])
        self.assertFalse(self.pending.exists())

    def test_different_task_still_completes_after_recovery(self):
        self.fail_write(self.path)
        self.run_cli("done", "second task")
        self.assertEqual(status.items(self.path.read_text().splitlines(), "Now"), [])
        log = self.log.read_text().splitlines()
        self.assertEqual((log.count("- first task"), log.count("- second task")), (1, 1))
        self.assertFalse(self.pending.exists())

    def test_retry_by_text_does_not_fail_or_finish_another(self):
        self.fail_write(self.path)
        self.run_cli("done", "first")
        self.assert_completed_once()

    def test_decision_recovers_pending_completion_before_recording(self):
        self.fail_write(self.path)
        self.run_cli("decide", "Use Postgres")
        self.assert_completed_once()
        self.assertIn("D-001: Use Postgres", self.path.read_text())


class DecideRecoveryTests(RecoveryTestCase):
    def setUp(self):
        super().setUp()
        self.command = "decide"
        self.args = SimpleNamespace(text=["Use Postgres"])
        self.pending = self.root / status.STATE / status.DECIDE_PENDING
        self.decisions = self.root / status.STATE / "decisions.md"
        self.original_decisions = self.decisions.read_text()

    def assert_recorded_once(self):
        entries = [line for line in self.decisions.read_text().splitlines() if status.DEC_RE.match(line)]
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].startswith("- D-001 ("))
        self.assertTrue(entries[0].endswith(": Use Postgres"))
        self.assertEqual(status.items(self.path.read_text().splitlines(), "Decisions"),
                         ["D-001: Use Postgres"])
        self.assertFalse(self.pending.exists())

    def test_invalid_status_changes_neither_decisions_nor_pending(self):
        self.path.write_text(self.original.replace("## Decisions", "## Removed"))
        with self.assertRaises(SystemExit):
            status.cmd_decide(self.root, self.args)
        self.assertEqual(self.decisions.read_text(), self.original_decisions)
        self.assertFalse(self.pending.exists())

    def test_pending_write_failure_changes_neither_file(self):
        self.fail_write(self.pending)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertEqual(self.decisions.read_text(), self.original_decisions)
        self.assertFalse(self.pending.exists())

    def test_interrupt_after_pending_save_can_retry(self):
        self.fail_write(self.pending, after=True)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertEqual(self.decisions.read_text(), self.original_decisions)
        self.run_cli("decide", "Use Postgres")
        self.assert_recorded_once()

    def test_decisions_write_failure_can_retry(self):
        self.fail_write(self.decisions)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertEqual(self.decisions.read_text(), self.original_decisions)
        self.assertTrue(self.pending.exists())
        self.run_cli("decide", "Use Postgres")
        self.assert_recorded_once()

    def test_interrupt_after_decisions_save_does_not_duplicate_entry(self):
        self.fail_write(self.decisions, after=True)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertIn(": Use Postgres", self.decisions.read_text())
        self.run_cli("decide", "Use Postgres")
        self.assert_recorded_once()

    def test_status_write_failure_recovers_summary_without_new_number(self):
        self.fail_write(self.path)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertIn(": Use Postgres", self.decisions.read_text())
        self.run_cli("decide", "Use Postgres")
        self.assert_recorded_once()

    def test_interrupt_after_status_save_does_not_duplicate_decision(self):
        self.fail_write(self.path, after=True)
        self.assertIn("D-001: Use Postgres", self.path.read_text())
        self.assertTrue(self.pending.exists())
        self.run_cli("decide", "Use Postgres")
        self.assert_recorded_once()

    def test_manual_status_edit_is_preserved_before_any_recovery_write(self):
        self.fail_write(self.decisions)
        edited = self.original.replace("## Goal\n- ", "## Goal\n- new goal")
        self.path.write_text(edited)
        result = subprocess.run([sys.executable, str(SOURCE), "decide", "Use Postgres"],
                                cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.path.read_text(), edited)
        self.assertEqual(self.decisions.read_text(), self.original_decisions)
        self.assertTrue(self.pending.exists())

    def test_manual_decisions_edit_is_preserved(self):
        self.fail_write(self.path)
        edited = self.decisions.read_text() + "- manual note\n"
        self.decisions.write_text(edited)
        result = subprocess.run([sys.executable, str(SOURCE), "decide", "Use Postgres"],
                                cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.decisions.read_text(), edited)
        self.assertEqual(self.path.read_text(), self.original)
        self.assertTrue(self.pending.exists())

    def test_completion_recovers_pending_decision_before_finishing_task(self):
        self.fail_write(self.path)
        self.run_cli("done", "1")
        self.assert_recorded_once()
        self.assertEqual(status.items(self.path.read_text().splitlines(), "Now"), ["second task"])
        self.assertIn("- first task", self.log.read_text())

    def test_different_decision_is_recorded_after_recovery(self):
        self.fail_write(self.path)
        self.run_cli("decide", "Use Redis")
        text = self.decisions.read_text()
        self.assertIn(": Use Postgres", text)
        self.assertIn("D-002 (", text)
        self.assertIn(": Use Redis", text)
        self.assertIn("D-002: Use Redis", self.path.read_text())
        self.assertFalse(self.pending.exists())

    def test_recovery_restores_latest_five_and_older_count(self):
        for number in range(1, 6):
            self.run_cli("decide", f"old choice {number}")
        self.fail_write(self.path)
        self.run_cli("decide", "Use Postgres")
        entries = [line for line in self.decisions.read_text().splitlines() if status.DEC_RE.match(line)]
        self.assertEqual(len(entries), 6)
        self.assertIn("D-006: Use Postgres", self.path.read_text())
        self.assertNotIn("D-001:", self.path.read_text())
        self.assertIn("(+1 older:", self.path.read_text())
        self.assertFalse(self.pending.exists())


suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case)
                           for case in (DoneRecoveryTests, DecideRecoveryTests))
result = unittest.TextTestRunner(stream=sys.stdout).run(suite)
failed = len(result.failures) + len(result.errors)
print(f"== {result.testsRun - failed} passed, {failed} failed")
sys.exit(0 if result.wasSuccessful() else 1)
