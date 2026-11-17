import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from tools.dropforge_feedback import REPO
from tools.dropforge_monthly import (
    MonthlyMaintenance,
    latest_windows_run,
    monthly_changes,
    windows_result,
)


PERIOD = "2026-12"
BRANCH = f"automation/monthly-{PERIOD}"
BASE = "a" * 40
HEAD = "b" * 40
OTHER = "c" * 40
NUMBER = 42
SOURCE = 'from collections.abc import Iterable\n\ndef rank(games: Iterable[str]):\n    return list(games)\n'
CHANGES = {"priority_actions.py": SOURCE.replace("list(games)", "sorted(games)")}


def plan(path, before, after):
    return {"decision": "patch", "edits": [{"path": path, "before": before, "after": after}]}


def workflow_run(**overrides):
    return {
        "id": 61,
        "run_number": 12,
        "run_attempt": 1,
        "head_sha": HEAD,
        "head_branch": BRANCH,
        "head_repository": {"full_name": REPO},
        "event": "pull_request",
        "pull_requests": [{"number": NUMBER}],
        "status": "completed",
        **overrides,
    }


def windows_job(**overrides):
    return {
        "name": "Windows",
        "status": "completed",
        "conclusion": "success",
        "steps": [
            {"name": "Run automated tests", "conclusion": "success"},
            {"name": "Create portable executable", "conclusion": "success"},
        ],
        **overrides,
    }


def pull_request(**overrides):
    return {
        "number": NUMBER,
        "state": "OPEN",
        "headRefOid": HEAD,
        "baseRefName": "main",
        "isCrossRepository": False,
        **overrides,
    }


class MonthlyChangesTests(unittest.TestCase):
    def test_accepts_scoped_pure_behavioral_improvement(self):
        files = {"priority_actions.py": SOURCE}
        request = plan("priority_actions.py", "list(games)", "sorted(games)")
        self.assertEqual(monthly_changes(files, request), CHANGES)
        self.assertEqual(files, {"priority_actions.py": SOURCE})

    def test_ignores_runs_where_no_patch_is_justified(self):
        for decision in ("ignore", "manual"):
            with self.subTest(decision=decision):
                self.assertEqual(monthly_changes({}, {"decision": decision, "edits": []}), {})

    def test_rejects_a_change_to_the_application_shell_and_workflows(self):
        for name in ("gui.py", ".github/workflows/feedback-release.yml"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                monthly_changes({name: "x = 1\n"}, plan(name, "1", "2"))

    def test_rejects_import_changes_and_new_io_or_dynamic_calls(self):
        changes = [
            ("from collections.abc import Iterable", "import pathlib\nfrom collections.abc import Iterable"),
            ("return list(games)", 'return open("settings.json").read()'),
            ("return list(games)", "return eval(games)"),
            ("return list(games)", "return games.__dict__"),
        ]
        for before, after in changes:
            with self.subTest(after=after), self.assertRaises(ValueError):
                monthly_changes({"priority_actions.py": SOURCE}, plan("priority_actions.py", before, after))

    def test_rejects_cosmetic_and_oversize_replacements(self):
        files = {"priority_actions.py": SOURCE}
        with self.assertRaisesRegex(ValueError, "does not change behavior"):
            monthly_changes(files, plan("priority_actions.py", "return list(games)", "return list(games)  # unchanged"))
        long_value = repr("a" * 2300)
        replacement = repr("b" * 2300)
        with self.assertRaisesRegex(ValueError, "too large"):
            monthly_changes(
                {"priority_actions.py": f"value = {long_value}\n"},
                plan("priority_actions.py", long_value, replacement),
            )


class WindowsValidationTests(unittest.TestCase):
    def test_selects_latest_attempt_of_latest_matching_run(self):
        selected = workflow_run(id=70, run_number=13, run_attempt=2)
        nonmatching = [
            workflow_run(run_number=99, head_sha=OTHER),
            workflow_run(run_number=99, head_branch="another"),
            workflow_run(run_number=99, head_repository={"full_name": "another/DropForge"}),
            workflow_run(run_number=99, event="push"),
            workflow_run(run_number=99, pull_requests=[{"number": NUMBER + 1}]),
        ]
        runs = [selected, workflow_run(run_number=13), *nonmatching, workflow_run(run_attempt=8)]
        self.assertIs(latest_windows_run(runs, HEAD, BRANCH, NUMBER), selected)
        self.assertIsNone(latest_windows_run(nonmatching, HEAD, BRANCH, NUMBER))

    def test_requires_successful_windows_tests_and_packaging(self):
        self.assertEqual(windows_result([windows_job()]), "passed")
        self.assertEqual(windows_result([windows_job(status="in_progress")]), "waiting")
        self.assertEqual(windows_result([windows_job(name="Ubuntu")]), "waiting")
        self.assertEqual(windows_result([windows_job(), windows_job()]), "waiting")
        self.assertEqual(windows_result([windows_job(conclusion="failure")]), "failed")
        self.assertEqual(windows_result([windows_job(steps=[])]), "failed")
        missing_compile = windows_job()
        missing_compile["steps"][1]["conclusion"] = "skipped"
        self.assertEqual(windows_result([missing_compile]), "failed")


class MonthlyMaintenanceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)
        self.maintenance = MonthlyMaintenance(argparse.Namespace(
            state_dir=path, gh=Path("gh"), git=Path("git"), gh_config_dir=path, codex=Path("codex"),
        ))

    def stub(self, name, **kwargs):
        context = patch.object(self.maintenance, name, **kwargs)
        self.addCleanup(context.stop)
        return context.start()

    def setup_run(self, *, checks="passed", main=BASE, initial=None, confirmed=None):
        github = self.stub("github", return_value="lorderon34\n")
        self.stub("remote_branch", side_effect=lambda branch: main if branch == "main" else "")
        self.stub("ensure_repo", return_value=BASE)
        proposed = self.stub("propose", return_value=CHANGES)
        install = self.stub("install_branch", return_value=HEAD)
        opened = self.stub("open_pr")
        windows = self.stub("wait_for_windows", return_value=checks)

        def lookup_pr(branch):
            self.assertEqual(branch, BRANCH)
            if not opened.called:
                return None
            if windows.called:
                return confirmed or pull_request()
            return initial or pull_request()

        self.stub("find_pr", side_effect=lookup_pr)
        return github, proposed, install, opened, windows

    def test_checks_latest_workflow_attempt_for_exact_pr_head(self):
        github = self.stub("github", side_effect=[
            json.dumps({"workflow_runs": [workflow_run(id=60), workflow_run(id=61, run_attempt=2)]}),
            json.dumps({"jobs": [windows_job()]}),
        ])
        self.assertEqual(self.maintenance.wait_for_windows(BRANCH, HEAD, NUMBER), "passed")
        query = f"repos/{REPO}/actions/workflows/ci.yml/runs?event=pull_request&head_sha={HEAD}&per_page=30"
        self.assertEqual(github.call_args_list, [
            call("api", query),
            call("api", f"repos/{REPO}/actions/runs/61/attempts/2/jobs?per_page=100"),
        ])

    def test_merges_matching_pr_with_verified_head_at_most_once_per_month(self):
        github, proposed, install, opened, windows = self.setup_run()
        initial = self.maintenance.run_month(PERIOD)
        self.assertEqual(initial, self.maintenance.run_month(PERIOD))
        proposed.assert_called_once_with(BASE, PERIOD)
        install.assert_called_once()
        opened.assert_called_once_with(BRANCH, PERIOD)
        windows.assert_called_once_with(BRANCH, HEAD, NUMBER)
        self.assertEqual([args for args in github.call_args_list if args.args[:2] == ("pr", "merge")], [
            call("pr", "merge", str(NUMBER), "-R", REPO, "--merge", "--match-head-commit", HEAD),
        ])

    def test_failed_build_leaves_pr_unmerged(self):
        github, _, _, _, _ = self.setup_run(checks="failed")
        self.assertIn("failed", self.maintenance.run_month(PERIOD))
        github.assert_called_once_with("api", "user", "--jq", ".login")

    def test_advanced_main_leaves_pr_unmerged_even_after_windows_checks(self):
        github, _, _, _, windows = self.setup_run(main=OTHER)
        result = self.maintenance.run_month(PERIOD)
        self.assertIn("main advanced", result)
        windows.assert_called_once_with(BRANCH, HEAD, NUMBER)
        github.assert_called_once_with("api", "user", "--jq", ".login")

    def test_mismatching_pr_head_is_rejected_before_windows_checks(self):
        github, _, _, _, windows = self.setup_run(initial=pull_request(headRefOid=OTHER))
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.maintenance.run_month(PERIOD)
        windows.assert_not_called()
        github.assert_called_once_with("api", "user", "--jq", ".login")

    def test_changed_pr_is_not_merged_after_windows_checks(self):
        github, _, _, _, windows = self.setup_run(confirmed=pull_request(headRefOid=OTHER))
        self.assertIn("changed", self.maintenance.run_month(PERIOD))
        windows.assert_called_once_with(BRANCH, HEAD, NUMBER)
        github.assert_called_once_with("api", "user", "--jq", ".login")

    def test_preview_leaves_month_state_untouched_and_never_writes_to_github(self):
        github = self.stub("github", return_value="lorderon34")
        self.stub("ensure_repo", return_value=BASE)
        propose = self.stub("propose", return_value=CHANGES)
        install = self.stub("install_branch")
        opened = self.stub("open_pr")
        before = self.maintenance.state_path.read_bytes()
        self.assertEqual(self.maintenance.run_month(PERIOD, preview=True), "preview: priority_actions.py")
        self.assertEqual(self.maintenance.state_path.read_bytes(), before)
        propose.assert_called_once_with(BASE, PERIOD)
        github.assert_called_once_with("api", "user", "--jq", ".login")
        install.assert_not_called()
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
