"""Exercise setup choices with real Git repositories and isolated Git config."""
import contextlib
import importlib.util
import io
import json
import os
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


class InitModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "project with spaces"
        self.root.mkdir()
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": str(self.base / "gitconfig"),
                    "GIT_CONFIG_NOSYSTEM": "1"}
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "test")
        self.ex = self.root / ".git/info/exclude"

    def git(self, *args, root=None):
        result = subprocess.run(["git", *args], cwd=root or self.root, env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def cli(self, *args, root=None, success=True, data=None):
        result = subprocess.run([sys.executable, str(SOURCE), *args], cwd=root or self.root,
                                env=self.env, input=data or "", capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def ignored(self, name, root=None):
        result = subprocess.run(["git", "check-ignore", "--no-index", "--", name],
                                cwd=root or self.root, env=self.env, capture_output=True, text=True)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.returncode == 0

    def record_paths(self):
        return [status.STATUS, f"{status.STATE}/decisions.md",
                f"{status.STATE}/log/{status.today()[:7]}.md"]

    def make_log(self):
        self.cli("claim", "finished work")
        self.cli("done")

    def commit_records(self):
        self.git("add", "--", status.STATUS, f"{status.STATE}/decisions.md")
        self.git("commit", "-qm", "work records")

    def test_new_noninteractive_init_needs_choice_without_creating_files(self):
        original = self.ex.read_bytes()
        out = self.cli("init", success=False).stdout
        self.assertIn("--local", out)
        self.assertIn("--git", out)
        self.assertFalse((self.root / status.STATUS).exists())
        self.assertFalse((self.root / status.STATE).exists())
        self.assertEqual(self.ex.read_bytes(), original)

    def test_interactive_choice_requires_an_answer_and_supports_both_modes(self):
        for answer, expected in (("1", "git"), ("2", "local")):
            with self.subTest(mode=expected), contextlib.redirect_stdout(io.StringIO()):
                with patch.object(status.sys, "stdin", SimpleNamespace(isatty=lambda: True)):
                    with patch("builtins.input", side_effect=["", answer]) as prompt:
                        self.assertEqual(status.choose_mode(), expected)
                        self.assertEqual(prompt.call_count, 2)

    def test_personal_records_and_link_stay_out_of_commits(self):
        self.cli("init", "--local", "--link")
        self.make_log()
        for name in self.record_paths() + [status.LINK_FILE]:
            self.assertTrue(self.ignored(name), name)
        self.git("add", "-A")
        self.assertEqual(self.git("ls-files"), "")

    def test_shared_records_are_visible_without_staging_or_committing(self):
        out = self.cli("init", "--git", "--link").stdout
        self.assertIn("at any time", out)
        self.make_log()
        for name in self.record_paths():
            self.assertTrue((self.root / name).exists())
            self.assertFalse(self.ignored(name), name)
        self.assertTrue(self.ignored(status.LINK_FILE))
        self.assertEqual(self.git("ls-files"), "")
        self.assertEqual(self.git("for-each-ref", "--format=%(refname)", "refs/heads/"), "")

    def test_shared_runtime_files_are_excluded_from_git_add(self):
        self.cli("init", "--git", "--link")
        self.make_log()
        for name in (f"{status.STATE}/.lock", f"{status.STATE}/.reminded",
                     f"{status.STATE}/{status.DONE_PENDING}", f"{status.STATE}/{status.DECIDE_PENDING}",
                     ".STATUS.md.example.tmp",
                     ".CLAUDE.local.md.example.tmp", f"{status.STATE}/.decisions.md.example.tmp",
                     f"{status.STATE}/log/.2026-11.md.example.tmp"):
            (self.root / name).write_text("local runtime data")
            self.assertTrue(self.ignored(name), name)
        self.git("add", "-A")
        self.assertEqual(set(self.git("ls-files").splitlines()), set(self.record_paths()))

    def test_legacy_personal_setup_can_switch_to_shared_without_changing_notes(self):
        self.cli("init", "--local")
        (self.root / status.STATUS).write_text("existing status\n")
        (self.root / status.STATE / "decisions.md").write_text("existing decisions\n")
        self.ex.write_text("# custom before\n/build/\n" + "\n".join(status.LEGACY_EXCLUDE) +
                           "\n# custom after\n/cache/\n")
        self.cli("init", "--git")
        self.assertEqual((self.root / status.STATUS).read_text(), "existing status\n")
        self.assertEqual((self.root / status.STATE / "decisions.md").read_text(), "existing decisions\n")
        self.assertTrue(self.ignored("build/example"))
        self.assertTrue(self.ignored("cache/example"))
        self.assertFalse(self.ignored(status.STATUS))
        self.assertFalse(self.ignored(f"{status.STATE}/decisions.md"))

    def test_rerun_keeps_each_mode_and_exclusions_unchanged(self):
        for mode in ("git", "local"):
            self.cli("init", f"--{mode}")
            previous = self.ex.read_bytes()
            self.cli("init")
            self.assertEqual(self.ex.read_bytes(), previous)
            self.assertEqual(self.ignored(status.STATUS), mode == "local")

    def test_setups_from_before_the_rename_keep_their_mode(self):
        for old, mode in (("personal", "local"), ("shared", "git")):
            self.cli("init", f"--{mode}")
            body = self.ex.read_text().replace(f"# where-were-we ({mode})", f"# where-were-we ({old})")
            self.ex.write_text(body)
            self.cli("init")
            text = self.ex.read_text()
            self.assertIn(f"# where-were-we ({mode})", text)
            self.assertNotIn(f"({old})", text)
            self.assertEqual(text.count(status.EXCLUDE_END), 1)
            self.assertEqual(self.ignored(status.STATUS), mode == "local")

    def test_existing_legacy_setup_does_not_ask_again(self):
        self.cli("init", "--local")
        self.ex.write_text("\n".join(status.LEGACY_EXCLUDE) + "\n")
        self.cli("init")
        self.assertTrue(self.ignored(status.STATUS))

    def test_shared_untracked_records_can_switch_back_to_personal(self):
        self.cli("init", "--git")
        original = (self.root / status.STATUS).read_bytes()
        self.cli("init", "--local")
        self.assertTrue(self.ignored(status.STATUS))
        self.assertEqual((self.root / status.STATUS).read_bytes(), original)
        self.assertEqual(self.git("ls-files"), "")

    def test_personal_refuses_tracked_records_without_changing_anything(self):
        self.cli("init", "--git")
        self.commit_records()
        before = (self.ex.read_bytes(), (self.root / status.STATUS).read_bytes(),
                  self.git("ls-files", "--stage"))
        self.cli("init", "--local", success=False)
        after = (self.ex.read_bytes(), (self.root / status.STATUS).read_bytes(),
                 self.git("ls-files", "--stage"))
        self.assertEqual(before, after)

    def test_personal_refuses_staged_status_without_creating_state(self):
        (self.root / status.STATUS).write_text("preexisting project notes\n")
        self.git("add", status.STATUS)
        original = self.ex.read_bytes()
        self.cli("init", "--local", success=False)
        self.assertFalse((self.root / status.STATE).exists())
        self.assertEqual(self.ex.read_bytes(), original)
        self.assertEqual(self.git("ls-files"), "STATUS.md\n")

    def test_tracked_records_can_switch_to_personal_after_explicit_untracking(self):
        self.cli("init", "--git")
        self.commit_records()
        before = {name: (self.root / name).read_bytes() for name in self.record_paths()[:2]}
        self.git("rm", "--cached", "--", *before)
        self.cli("init", "--local")
        for name, content in before.items():
            self.assertEqual((self.root / name).read_bytes(), content)
            self.assertTrue(self.ignored(name))
        self.assertEqual(self.git("ls-files"), "")
        self.assertIn("STATUS.md", self.git("ls-tree", "--name-only", "HEAD"))

    def test_shared_preserves_existing_staging_and_other_gitignore_rules(self):
        (self.root / ".gitignore").write_text("build/\n")
        (self.root / "source.txt").write_text("user changes\n")
        self.git("add", "source.txt")
        previous = self.git("ls-files", "--stage")
        self.cli("init", "--git")
        self.assertEqual(self.git("ls-files", "--stage"), previous)
        self.assertEqual((self.root / ".gitignore").read_text(), "build/\n")

    def test_shared_reports_other_ignore_rules_and_preserves_previous_mode(self):
        self.cli("init", "--local")
        original = self.ex.read_bytes()
        (self.root / ".gitignore").write_text("/STATUS.md\n")
        self.cli("init", "--git", success=False)
        self.assertEqual(self.ex.read_bytes(), original)
        self.assertEqual((self.root / ".gitignore").read_text(), "/STATUS.md\n")
        self.assertTrue(self.ignored(f"{status.STATE}/decisions.md"))

    def test_shared_does_not_remove_user_exclusions_outside_its_block(self):
        self.ex.write_text(self.ex.read_text() + "/STATUS.md\n")
        original = self.ex.read_bytes()
        self.cli("init", "--git", success=False)
        self.assertEqual(self.ex.read_bytes(), original)
        self.assertFalse((self.root / status.STATE).exists())

    def test_shared_requires_git_but_personal_works_without_git(self):
        other = self.base / "no git"
        other.mkdir()
        self.cli("init", "--git", root=other, success=False)
        self.assertEqual(list(other.iterdir()), [])
        self.cli("init", "--local", root=other)
        self.cli("init", root=other)
        self.assertTrue((other / status.STATUS).exists())

    def test_cloned_records_keep_shared_mode_and_ignore_runtime_on_first_write(self):
        self.cli("init", "--git")
        self.commit_records()
        clone = self.base / "clone"
        self.git("clone", "-q", str(self.root), str(clone))
        self.cli("claim", "new task", root=clone)
        self.assertFalse(self.ignored(status.STATUS, root=clone))
        for name in (f"{status.STATE}/.lock", f"{status.STATE}/.reminded",
                     f"{status.STATE}/{status.DONE_PENDING}", f"{status.STATE}/{status.DECIDE_PENDING}"):
            self.assertTrue(self.ignored(name, root=clone))
        before = (clone / ".git/info/exclude").read_bytes()
        self.cli("init", root=clone)
        self.assertEqual((clone / ".git/info/exclude").read_bytes(), before)

    def test_stop_hook_in_clone_keeps_reminder_local_without_init(self):
        self.cli("init", "--git")
        self.commit_records()
        clone = self.base / "clone"
        self.git("clone", "-q", str(self.root), str(clone))
        os.utime(clone / status.STATUS, (0, 0))
        out = self.cli("hook-stop", root=clone, data=json.dumps({"cwd": str(clone)})).stdout
        self.assertEqual(json.loads(out)["decision"], "block")
        self.assertTrue(self.ignored(f"{status.STATE}/.reminded", root=clone))

    def test_conflicting_flags_make_no_files(self):
        self.cli("init", "--local", "--git", success=False)
        self.assertFalse((self.root / status.STATUS).exists())


suite = unittest.defaultTestLoader.loadTestsFromTestCase(InitModeTests)
result = unittest.TextTestRunner(stream=sys.stdout).run(suite)
failed = len(result.failures) + len(result.errors)
print(f"== {result.testsRun - failed} passed, {failed} failed")
sys.exit(0 if result.wasSuccessful() else 1)
