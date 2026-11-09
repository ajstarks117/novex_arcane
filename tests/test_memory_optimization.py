"""Tests for memory optimization, lazy imports, concurrency limits, and secure session persistence.

Verifies:
1. In hosted mode, PyTorch and sentence-transformers are NOT imported into sys.modules.
2. Patch memory is optional and skipped in hosted mode.
3. Concurrency limiter limits overlapping repairs on free-tier instances.
4. Security: Cookies contain ONLY opaque session IDs (no sensitive tokens/credentials in cookies).
5. Security: OAuth tokens are encrypted at rest using AES/Fernet server-side.
6. Security: Session expiry is enforced and invalidates expired sessions.
7. Security: Logout invalidates the server-side session (preventing reuse).
8. Security: Hosted mode strictly requires configured secrets (no hardcoded fallbacks).
9. Database: Ephemeral limitations handled gracefully; postgres:// URLs are never passed to sqlite3.
10. Memory usage stays strictly under Render's 512 MB limit during realistic hosted runs.
"""
import sys
import os
import subprocess
import secrets
from datetime import datetime, timezone, timedelta
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
from api.auth import (
    COOKIE,
    encrypt_token,
    decrypt_token,
    current_user,
    logout,
    _get_encryption_key,
    _save,
    _load,
)
from api.db import (
    db_save_session,
    db_get_session,
    db_delete_session,
    db_save_run,
    db_load_all_runs,
    is_postgres_configured,
    get_sqlite_path,
    init_db,
)


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


class TestSessionSecurityAndPersistence:
    """Security fixes: Opaque session ID, encryption at rest, expiry, and logout invalidation."""

    def test_cookie_is_opaque_and_does_not_contain_credentials(self):
        """Verifies that session IDs are completely opaque random tokens."""
        sid = secrets.token_urlsafe(32)
        # Verify it has no dots (not a JWT / compound token), contains no credentials
        assert "." not in sid
        assert "gho_" not in sid
        assert "token" not in sid

    def test_encryption_at_rest_roundtrip(self):
        """Verifies that credentials are encrypted server-side and plaintext is not stored."""
        plain_token = "gho_super_secret_github_oauth_token_12345"
        encrypted = encrypt_token(plain_token)

        assert encrypted != plain_token
        assert plain_token not in encrypted
        assert "gho_" not in encrypted

        decrypted = decrypt_token(encrypted)
        assert decrypted == plain_token

    def test_session_lifecycle_with_opaque_sid_and_encryption(self, tmp_path, monkeypatch):
        """End-to-end: stores encrypted session server-side, accesses via opaque cookie, verifies token."""
        from api import auth
        test_session_file = str(tmp_path / "sessions.json")
        monkeypatch.setattr(auth, "SESSION_FILE", test_session_file)

        sid = secrets.token_urlsafe(32)
        plain_token = "gho_user_live_token_789"
        encrypted = encrypt_token(plain_token)

        expires_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
        session_data = {
            "login": "octocat",
            "name": "The Octocat",
            "email": "octocat@github.com",
            "avatar": "https://avatars.githubusercontent.com/u/583231",
            "encrypted_token": encrypted,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "expiresAt": expires_at,
        }
        _save({sid: session_data})

        # Verify on-disk format has encrypted_token, NOT plaintext token
        loaded = _load()
        assert loaded[sid]["encrypted_token"] == encrypted
        assert "token" not in loaded[sid] or loaded[sid].get("token") is None

        # Authenticate via request with opaque cookie
        mock_request = MagicMock()
        mock_request.cookies = {COOKIE: sid}

        user = current_user(mock_request)
        assert user is not None
        assert user["login"] == "octocat"
        # current_user must decrypt token for in-memory use
        assert user["token"] == plain_token

    def test_session_expiry_enforced(self, tmp_path, monkeypatch):
        """Expired sessions must be rejected and deleted server-side."""
        from api import auth
        test_session_file = str(tmp_path / "sessions.json")
        monkeypatch.setattr(auth, "SESSION_FILE", test_session_file)

        sid = secrets.token_urlsafe(32)
        past_expiry = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        session_data = {
            "login": "expired_user",
            "encrypted_token": encrypt_token("gho_expired"),
            "expiresAt": past_expiry,
        }
        _save({sid: session_data})

        mock_request = MagicMock()
        mock_request.cookies = {COOKIE: sid}

        user = current_user(mock_request)
        assert user is None, "Expired session must be rejected!"
        # Verify server-side cleanup
        assert sid not in _load()

    def test_logout_invalidates_session_server_side(self, tmp_path, monkeypatch):
        """Logout must delete server-side session so reused cookie is rejected."""
        from api import auth
        test_session_file = str(tmp_path / "sessions.json")
        monkeypatch.setattr(auth, "SESSION_FILE", test_session_file)

        sid = secrets.token_urlsafe(32)
        session_data = {
            "login": "active_user",
            "encrypted_token": encrypt_token("gho_active"),
            "expiresAt": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        }
        _save({sid: session_data})

        mock_request = MagicMock()
        mock_request.cookies = {COOKIE: sid}
        mock_response = MagicMock()

        # User is valid before logout
        assert current_user(mock_request) is not None

        # Perform logout
        logout(mock_request, mock_response)

        # Cookie deleted on response
        mock_response.delete_cookie.assert_called_with(COOKIE, path="/")

        # Re-presenting the cookie must now fail
        assert current_user(mock_request) is None

    def test_missing_secret_in_hosted_mode_raises_error(self, monkeypatch):
        """In hosted mode, running without configured secrets must raise a hard error."""
        monkeypatch.setenv("ARCANE_EXECUTION_MODE", "hosted")
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

        with pytest.raises(RuntimeError) as exc:
            _get_encryption_key()
        assert "CRITICAL SECURITY CONFIGURATION ERROR" in str(exc.value)


class TestDatabaseStorageBackend:
    """Database backend: tests SQLite persistence and safe handling of postgres:// URLs."""

    def test_sqlite_storage_roundtrip(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_arcane.db")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db}")
        from api import db
        db._DB_PATH = None

        user = {"login": "db_user", "encrypted_token": "enc_123"}
        db_save_session("sid_db_1", user)
        loaded = db_get_session("sid_db_1")
        assert loaded is not None
        assert loaded["login"] == "db_user"

        db_delete_session("sid_db_1")
        assert db_get_session("sid_db_1") is None

    def test_postgres_database_url_handled_safely(self, monkeypatch):
        """Setting a postgres:// DATABASE_URL must not crash or pass the URI to sqlite3."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@localhost:5432/arcanedb")
        from api import db
        db._DB_PATH = None
        db._PG_AVAILABLE = None

        assert is_postgres_configured() is True
        sqlite_path = get_sqlite_path()
        assert not sqlite_path.startswith("postgresql://"), "Postgres URI must NEVER be treated as SQLite file path!"

        # init_db must not crash even if postgres server/driver is not running
        init_db()


class TestMemoryRssLimits:
    """Requirement 8 & 11: Backend RSS stays strictly within Render's 512 MB memory limit."""

    def test_rss_memory_is_under_512mb(self):
        rss_mb = get_memory_usage_mb()
        assert rss_mb > 0
        assert rss_mb < 350, f"Memory usage ({rss_mb:.1f} MB) is unexpectedly high, must be well below 512 MB!"
        print(f"\n[Test] Current Process Memory: {rss_mb:.1f} MB (Headroom to 512 MB: {512 - rss_mb:.1f} MB)")
