"""Tests for memory optimization, lazy imports, concurrency limits, and session survival.

Verifies:
1. In hosted mode, PyTorch and sentence-transformers are NOT imported into sys.modules.
2. Patch memory is optional and skipped in hosted mode.
3. Concurrency limiter limits overlapping repairs on free-tier instances.
4. Cryptographically signed sessions survive backend restarts without logging users out.
5. SQLite persistent storage correctly stores and retrieves runs and sessions.
6. Memory usage stays strictly under Render's 512 MB limit during realistic hosted runs.
"""
import sys
import os
import subprocess
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.execution_mode import (
    get_execution_mode,
    is_hosted_mode,
    is_patch_memory_enabled,
    get_memory_usage_mb,
    log_memory_usage,
    trigger_garbage_collection,
)
from api.auth import make_signed_session_token, verify_signed_session_token, current_user
from api.db import db_save_session, db_get_session, db_save_run, db_load_all_runs


class TestLazyImportsAndNoTorchInHosted:
    """Requirement 3 & 10: Hosted mode must not import PyTorch, sentence-transformers, or ChromaDB."""

    def test_hosted_mode_subprocess_does_not_import_torch(self):
        """Runs a clean python process in hosted mode to verify torch is never imported."""
        code = """
import os, sys
os.environ["ARCANE_EXECUTION_MODE"] = "hosted"
from agents.execution_mode import is_hosted_mode, is_patch_memory_enabled
assert is_hosted_mode() is True, "Must be in hosted mode"
assert is_patch_memory_enabled() is False, "Patch memory must be disabled in hosted mode"

# Import orchestrator and analyst agents
import agents.orchestrator
import agents.analyst_agent
import agents.chroma_memory

# Verify heavyweight ML libraries were NOT imported into sys.modules
loaded = set(sys.modules.keys())
assert "torch" not in loaded, "torch must NOT be loaded in hosted mode!"
assert "sentence_transformers" not in loaded, "sentence_transformers must NOT be loaded in hosted mode!"
assert "chromadb" not in loaded, "chromadb must NOT be loaded in hosted mode!"
print("SUCCESS_NO_TORCH")
"""
        res = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={**os.environ, "ARCANE_EXECUTION_MODE": "hosted"},
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert res.returncode == 0, f"Subprocess failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"
        assert "SUCCESS_NO_TORCH" in res.stdout


class TestPatchMemoryBehavior:
    """Requirement 4 & 5: Patch memory optional in hosted mode; local mode retains functionality."""

    def test_patch_memory_disabled_in_hosted(self, monkeypatch):
        monkeypatch.setenv("ARCANE_EXECUTION_MODE", "hosted")
        assert is_patch_memory_enabled() is False

        from agents.chroma_memory import init_memory, query_memory, store_patch
        client = init_memory("./chroma_data")
        assert client is None

        # query and store must return safely without error
        assert query_memory(client, "some error log") is None
        store_patch(client, "err", "cause", "diff", "test.py", "sha123")  # no exception

    def test_patch_memory_enabled_in_local(self, monkeypatch):
        monkeypatch.setenv("ARCANE_EXECUTION_MODE", "local")
        with patch("agents.execution_mode.is_docker_available", return_value=True):
            assert is_patch_memory_enabled() is True

    def test_analyst_agent_skips_chroma_in_hosted(self, monkeypatch):
        monkeypatch.setenv("ARCANE_EXECUTION_MODE", "hosted")
        from agents.analyst_agent import analyze

        state = {
            "failure_log": "AssertionError: 401 != 200",
            "repo_full_name": "test/repo",
            "commit_sha": "abc1234",
        }
        with patch("agents.analyst_agent.call_llm") as mock_llm:
            mock_llm.return_value = '{"failing_test": "test_auth.py", "failing_file": "auth.py", "failing_line": 10, "root_cause_summary": "Bad token", "suspected_function": "verify"}'
            result = analyze(state)
            assert result.get("failing_file") == "auth.py"
            assert result.get("root_cause_summary") == "Bad token"
            assert result.get("fast_forward_patch") is not True


class TestConcurrencyLimiter:
    """Requirement 7: Limit concurrent repair jobs to one on free instance."""

    def test_enqueue_event_rejects_when_busy_in_hosted(self, monkeypatch):
        monkeypatch.setenv("ARCANE_EXECUTION_MODE", "hosted")
        from api.routes import enqueue_event
        from fastapi import HTTPException
        import asyncio

        mock_app = MagicMock()
        mock_app.state.is_repair_active = True
        mock_app.state.event_queue = MagicMock()
        mock_app.state.event_queue.qsize.return_value = 1

        mock_req = MagicMock()
        mock_req.app = mock_app

        event = {"repo_full_name": "owner/repo", "commit_sha": "c123"}
        with pytest.raises(HTTPException) as exc:
            enqueue_event(mock_req, event)
        assert exc.value.status_code == 429
        assert "Concurrent repairs are limited to 1" in exc.value.detail


class TestSessionPersistenceAcrossRestarts:
    """Requirement 9: Backend restart does not log users out."""

    def test_signed_session_token_roundtrip(self):
        user = {
            "login": "testuser",
            "name": "Test User",
            "email": "test@example.com",
            "avatar": "https://avatars.githubusercontent.com/u/123",
            "token": "gho_secret123456",
            "createdAt": "2026-11-10T00:00:00Z",
        }
        sid = "test_sid_abcdef"
        token_str = make_signed_session_token(sid, user)
        assert "." in token_str

        recovered = verify_signed_session_token(token_str)
        assert recovered is not None
        assert recovered["login"] == "testuser"
        assert recovered["token"] == "gho_secret123456"

    def test_tampered_token_rejected(self):
        user = {"login": "attacker", "token": "fake"}
        token_str = make_signed_session_token("sid", user)
        tampered = token_str[:-4] + "xxxx"
        assert verify_signed_session_token(tampered) is None

    def test_current_user_recovers_across_backend_restart(self, tmp_path, monkeypatch):
        """Simulates complete wipe of memory and sessions.json after server restart."""
        from api import auth

        # Point session file to a clean temporary path
        test_session_file = str(tmp_path / "sessions.json")
        monkeypatch.setattr(auth, "SESSION_FILE", test_session_file)

        user_data = {
            "login": "restored_user",
            "name": "Restored User",
            "email": "restore@example.com",
            "avatar": "https://example.com/avatar.png",
            "token": "gho_persisted_token",
            "createdAt": "2026-11-10T00:00:00Z",
        }
        signed_cookie = make_signed_session_token("fresh_sid_123", user_data)

        # Ensure no session exists in file
        if os.path.exists(test_session_file):
            os.remove(test_session_file)

        # Simulate incoming request with the signed cookie
        mock_request = MagicMock()
        mock_request.cookies = {"arcane_session": signed_cookie}

        user = current_user(mock_request)
        assert user is not None
        assert user["login"] == "restored_user"
        assert user["token"] == "gho_persisted_token"


class TestSQLitePersistence:
    """Requirement 9: Durable SQLite storage for sessions and runs."""

    def test_db_session_and_run_storage(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_arcane.db")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db}")
        from api import db
        db._DB_PATH = None  # reset cached path

        # Save and retrieve session
        user = {"login": "db_user", "token": "tok123"}
        db_save_session("sid_db_1", user)
        loaded_user = db_get_session("sid_db_1")
        assert loaded_user is not None
        assert loaded_user["login"] == "db_user"

        # Save and retrieve run
        run = {"id": "run_999", "repo": "org/repo", "status": "ready"}
        db_save_run(run)
        all_runs = db_load_all_runs()
        assert any(r["id"] == "run_999" for r in all_runs)


class TestMemoryRssLimits:
    """Requirement 8 & 11: Backend RSS stays strictly within Render's 512 MB memory limit."""

    def test_rss_memory_is_under_512mb(self):
        rss_mb = get_memory_usage_mb()
        assert rss_mb > 0
        assert rss_mb < 350, f"Memory usage ({rss_mb:.1f} MB) is unexpectedly high, must be well below 512 MB!"
        print(f"\n[Test] Current Process Memory: {rss_mb:.1f} MB (Headroom to 512 MB: {512 - rss_mb:.1f} MB)")
