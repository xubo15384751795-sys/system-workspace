"""Default-branch CI visibility.

Branch protection is unavailable on this repo (private, free plan → 403), so
nothing server-side stops a red commit reaching main. 0e3b9c2 left merge-gate
red on main for a day unnoticed. This check is the other half of the local
pre-push gate: it makes a red default branch visible.
"""
from __future__ import annotations

import json

from scripts.commands.ci import check_main_ci_status as mod


def _stub_gh(monkeypatch, payload):
    monkeypatch.setattr(mod, "_gh_run_list", lambda branch, workflow: payload)


class TestCheckState:
    def test_failure_conclusion_is_failing(self, monkeypatch):
        _stub_gh(monkeypatch, [{"conclusion": "failure", "status": "completed",
                                "headSha": "3f022d2dabc", "displayTitle": "t",
                                "url": "u", "createdAt": "2026-07-31T12:16:14Z"}])
        result = mod.check("main", "ci.yml")
        assert result["state"] == "failing"
        assert result["head_sha"] == "3f022d2d"

    def test_success_is_ok(self, monkeypatch):
        _stub_gh(monkeypatch, [{"conclusion": "success", "status": "completed"}])
        assert mod.check("main", "ci.yml")["state"] == "ok"

    def test_in_progress_is_not_reported_as_failing(self, monkeypatch):
        """A run still going is not a red branch — notifying would cry wolf."""
        _stub_gh(monkeypatch, [{"conclusion": None, "status": "in_progress"}])
        assert mod.check("main", "ci.yml")["state"] == "running"

    def test_timed_out_counts_as_failing(self, monkeypatch):
        _stub_gh(monkeypatch, [{"conclusion": "timed_out", "status": "completed"}])
        assert mod.check("main", "ci.yml")["state"] == "failing"

    def test_cancelled_is_not_failing(self, monkeypatch):
        """A cancelled run is a human action, not a broken branch."""
        _stub_gh(monkeypatch, [{"conclusion": "cancelled", "status": "completed"}])
        assert mod.check("main", "ci.yml")["state"] == "ok"

    def test_gh_unavailable_is_distinct_from_failing(self, monkeypatch):
        """Missing gh must not be reported as a red branch."""
        _stub_gh(monkeypatch, None)
        assert mod.check("main", "ci.yml")["state"] == "unavailable"

    def test_no_runs_is_distinct_from_failing(self, monkeypatch):
        _stub_gh(monkeypatch, [])
        assert mod.check("main", "ci.yml")["state"] == "no_runs"


class TestMainExitCodesAndNotification:
    def test_failing_notifies_and_exits_one(self, monkeypatch, tmp_path, capsys):
        sent: list[tuple[str, str]] = []
        state = tmp_path / "main_ci_watch_notified.json"
        monkeypatch.setattr(mod, "_NOTIFY_STATE", state)
        _stub_gh(monkeypatch, [{"conclusion": "failure", "status": "completed",
                                "headSha": "abcdef1234", "displayTitle": "broke it",
                                "url": "https://example/run", "createdAt": "x"}])
        monkeypatch.setattr(mod, "notify_failure",
                            lambda t, m: sent.append((t, m)) or True)
        assert mod.main([]) == 1
        assert len(sent) == 1
        assert "main CI is red" in sent[0][0]
        assert "abcdef12" in sent[0][1]

    def test_failing_same_sha_does_not_renotify(self, monkeypatch, tmp_path, capsys):
        sent: list[tuple[str, str]] = []
        state = tmp_path / "main_ci_watch_notified.json"
        monkeypatch.setattr(mod, "_NOTIFY_STATE", state)
        _stub_gh(monkeypatch, [{"conclusion": "failure", "status": "completed",
                                "headSha": "abcdef1234", "displayTitle": "broke it",
                                "url": "https://example/run", "createdAt": "x"}])
        monkeypatch.setattr(mod, "notify_failure",
                            lambda t, m: sent.append((t, m)) or True)
        assert mod.main([]) == 1
        assert mod.main([]) == 1
        assert len(sent) == 1
        assert "already notified" in capsys.readouterr().err

    def test_ok_clears_dedupe_and_is_silent(self, monkeypatch, tmp_path):
        sent: list[tuple[str, str]] = []
        state = tmp_path / "main_ci_watch_notified.json"
        state.write_text('{"last_notified_sha": "abcdef12", "state": "failing"}\n')
        monkeypatch.setattr(mod, "_NOTIFY_STATE", state)
        _stub_gh(monkeypatch, [{"conclusion": "success", "status": "completed"}])
        monkeypatch.setattr(mod, "notify_failure",
                            lambda t, m: sent.append((t, m)) or True)
        assert mod.main([]) == 0
        assert sent == []
        assert not state.exists()

    def test_unavailable_exits_two_without_notifying(self, monkeypatch):
        sent: list[tuple[str, str]] = []
        _stub_gh(monkeypatch, None)
        monkeypatch.setattr(mod, "notify_failure",
                            lambda t, m: sent.append((t, m)) or True)
        assert mod.main([]) == 2
        assert sent == []

    def test_json_output_is_parseable(self, monkeypatch, capsys):
        _stub_gh(monkeypatch, [{"conclusion": "success", "status": "completed"}])
        mod.main(["--json"])
        assert json.loads(capsys.readouterr().out)["state"] == "ok"
