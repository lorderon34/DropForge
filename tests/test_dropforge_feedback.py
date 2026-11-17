import argparse
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tools.dropforge_feedback import (
    BRANCH_PREFIX,
    Poller,
    actor_environment,
    apply_plan,
    available_events,
    request_plan,
)


WHEN = "2026-11-17T08:00:00Z"
LATER = "2026-11-17T08:01:00Z"
ISSUE_URL = "https://api.github.com/repos/lorderon34/DropForge/issues/7"


def issue(identifier, **overrides):
    return {
        "id": identifier,
        "number": 7,
        "created_at": WHEN,
        "user": {"type": "User"},
        "body": "A barra de progresso se sobrepõe ao texto.",
        **overrides,
    }


def comment(identifier, **overrides):
    return issue(identifier, issue_url=ISSUE_URL, created_at=LATER, **overrides)


def plan(path, before, after):
    return {"decision": "patch", "edits": [{"path": path, "before": before, "after": after}]}


class AvailableEventsTests(unittest.TestCase):
    def test_orders_open_issue_and_comment_and_bounds_public_text(self):
        results = available_events([issue(3, body="á" * 4000)], [comment(2)], WHEN)
        self.assertEqual([event["id"] for event in results], ["issue-3", "comment-2"])
        self.assertEqual([event["number"] for event in results], [7, 7])
        self.assertEqual(len(results[0]["body"]), 3200)

    def test_ejects_old_bots_pull_requests_empty_and_foreign_comments(self):
        issues = [
            issue(1, created_at="2026-11-17T07:59:59Z"),
            issue(2, user={"type": "Bot"}),
            issue(3, pull_request={}),
            issue(4, body=""),
        ]
        comments = [
            issue(5, issue_url=ISSUE_URL.replace("DropForge", "Other")),
            issue(6, issue_url=ISSUE_URL + "/../../contents"),
        ]
        self.assertEqual(available_events(issues, comments, WHEN), [])


class ApplyPlanTests(unittest.TestCase):
    def setUp(self):
        self.files = {
            "gui.py": 'heading = "Progresso"\nfooter = "Progresso"\n',
            "lang/Português.json": '{"heading": "Progresso"}\n',
            ".github/workflows/publish.yml": "name: Workflows\n",
        }

    def test_updates_only_the_anchored_text_and_keeps_original_input(self):
        fixed = apply_plan(self.files, plan("gui.py", 'heading = "Progresso"', 'heading = "Campanha"'))
        self.assertEqual(fixed, {"gui.py": 'heading = "Campanha"\nfooter = "Progresso"\n'})
        self.assertTrue(self.files["gui.py"].startswith('heading = "Progresso"'))

    def test_ignores_manual_empty_and_identity_changes(self):
        self.assertEqual(apply_plan(self.files, {"decision": "manual", "edits": []}), {})
        self.assertEqual(apply_plan(self.files, plan("gui.py", "heading", "heading")), {})
        with self.assertRaises(ValueError):
            apply_plan(self.files, {"decision": "patch", "edits": []})

    def test_rejects_workflows_unlisted_files_and_unsafe_anchors(self):
        cases = [
            plan(".github/workflows/publish.yml", "Workflows", "Untrusted"),
            plan("../gui.py", "heading", "summary"),
            plan("campaign_agenda.py", "before", "after"),
            plan("gui.py", "Progresso", "Campanha"),
            plan("gui.py", "missing", "Campanha"),
            plan("gui.py", "", "Campanha"),
            plan("gui.py", "heading", "X" * 5001),
        ]
        for proposal in cases:
            with self.subTest(proposal=proposal["edits"][0]["path"]), self.assertRaises(ValueError):
                apply_plan(self.files, proposal)

    def test_rejects_invalid_python_and_json(self):
        with self.assertRaises(SyntaxError):
            apply_plan(self.files, plan("gui.py", 'heading = "Progresso"', "if :"))
        with self.assertRaises(json.JSONDecodeError):
            apply_plan(self.files, plan("lang/Português.json", '"Progresso"', "unquoted"))


class RequestPlanTests(unittest.TestCase):
    def test_environment_drops_credential_variables(self):
        environment = {"Path": "parent-path", "GH_TOKEN": "fake", "OPENAI_API_KEY": "fake"}
        with patch.dict(os.environ, environment, clear=True):
            result = actor_environment()
        self.assertEqual({key.upper(): value for key, value in result.items()}, {"PATH": "parent-path"})

    def test_tool_activity_invalidates_plan_even_if_final_output_matches_schema(self):
        response = "\n".join(
            json.dumps(event) for event in (
                {"type": "item.completed", "item": {"type": "command_execution"}},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": '{"decision":"ignore","edits":[]}'},
                },
            )
        )
        with (
            tempfile.TemporaryDirectory() as root,
            patch("tools.dropforge_feedback.run", return_value=response),
            self.assertRaisesRegex(ValueError, "tool action"),
        ):
            request_plan(Path("codex"), Path(root), {})


class PollerTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enter_temp_directory()
        self.args = argparse.Namespace(
            state_dir=Path(tmp), gh=Path("gh"), codex=Path("codex"), git=Path("git"),
            gh_config_dir=Path(tmp),
        )
        with patch(
            "tools.dropforge_feedback.utc_now",
            return_value=datetime(2026, 11, 17, 8, tzinfo=timezone.utc),
        ):
            self.poller = Poller(self.args)
        self.event = available_events([issue(1)], [], WHEN)[0]

    def enter_temp_directory(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return directory.name

    def test_check_mode_reads_without_processing_or_changing_state(self):
        before = self.poller.state_path.read_bytes()
        with (
            patch.object(self.poller, "github", return_value="lorderon34\n"),
            patch.object(self.poller, "events", return_value=[self.event]) as events,
            patch.object(self.poller, "handle") as handle,
        ):
            self.poller.poll(check=True)
        events.assert_called_once()
        handle.assert_not_called()
        self.assertEqual(self.poller.state_path.read_bytes(), before)

    def test_repeated_poll_does_not_repeat_a_processed_event(self):
        with (
            patch.object(self.poller, "github", return_value="lorderon34"),
            patch.object(self.poller, "events", return_value=[self.event]),
            patch.object(self.poller, "handle", return_value="draft") as handle,
        ):
            self.poller.poll(check=False)
            self.poller.poll(check=False)
        handle.assert_called_once_with(self.event)
        self.assertEqual(json.loads(self.poller.state_path.read_text())["seen"], {"issue-1": WHEN})

    def test_wrong_account_is_rejected_before_listing_events(self):
        with (
            patch.object(self.poller, "github", return_value="another-user"),
            patch.object(self.poller, "events") as events,
            self.assertRaises(ValueError),
        ):
            self.poller.poll(check=False)
        events.assert_not_called()

    def test_existing_unowned_branch_is_not_published(self):
        details = json.dumps({"state": "open", "title": "Barra de progresso"})
        with (
            patch.object(self.poller, "github", side_effect=[details, "[]"]),
            patch.object(self.poller, "remote_branch", return_value="remote-commit"),
            patch.object(self.poller, "open_draft") as draft,
        ):
            self.assertEqual(self.poller.handle(self.event), "reserved-branch")
        draft.assert_not_called()

    def test_pending_own_branch_resumes_draft_without_running_agent(self):
        branch = f"{BRANCH_PREFIX}7"
        self.poller.state["pending"][branch] = "remote-commit"
        details = json.dumps({"state": "open", "title": "Barra de progresso"})
        with (
            patch.object(self.poller, "github", side_effect=[details, "[]"]),
            patch.object(self.poller, "remote_branch", return_value="remote-commit"),
            patch.object(self.poller, "open_draft") as draft,
            patch("tools.dropforge_feedback.request_plan") as agent,
        ):
            self.assertEqual(self.poller.handle(self.event), "draft")
        draft.assert_called_once_with(branch, 7)
        agent.assert_not_called()
        self.assertNotIn(branch, self.poller.state["pending"])


if __name__ == "__main__":
    unittest.main()
