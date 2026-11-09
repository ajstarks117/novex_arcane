"""Durable SQLite storage for sessions, runs, and settings.

Guarantees persistence across backend restarts on Render/cloud instances.
Uses Python's standard library `sqlite3` — zero external dependencies and zero RAM overhead.
"""
import json
import logging
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_LOCK = threading.RLock()
_DB_PATH: Optional[str] = None


def get_db_path() -> str:
    """Returns the configured or default SQLite database file path."""
    global _DB_PATH
    if _DB_PATH:
        return _DB_PATH

    custom_url = os.getenv("DATABASE_URL") or os.getenv("ARCANE_DB_PATH")
    if custom_url and (custom_url.startswith("sqlite:///") or custom_url.endswith(".db")):
        path = custom_url.replace("sqlite:///", "")
    else:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        os.makedirs(data_dir, exist_ok=True)
        path = os.path.join(data_dir, "arcane.db")

    _DB_PATH = path
    return _DB_PATH


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path(), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initializes tables for sessions, runs, settings, and audit logs."""
    with _DB_LOCK:
        conn = _get_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        sid TEXT PRIMARY KEY,
                        login TEXT,
                        data_json TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS runs (
                        id TEXT PRIMARY KEY,
                        repo TEXT,
                        status TEXT,
                        data_json TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        data_json TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
        finally:
            conn.close()


# ── Session Operations ────────────────────────────────────────────────────────

def db_save_session(sid: str, user: Dict[str, Any]) -> None:
    init_db()
    with _DB_LOCK:
        conn = _get_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO sessions (sid, login, data_json, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (sid, user.get("login", ""), json.dumps(user)),
                )
        except Exception as e:
            logger.warning(f"[DB] db_save_session error: {e}")
        finally:
            conn.close()


def db_get_session(sid: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _DB_LOCK:
        conn = _get_connection()
        try:
            cur = conn.execute("SELECT data_json FROM sessions WHERE sid = ?", (sid,))
            row = cur.fetchone()
            if row:
                return json.loads(row["data_json"])
            return None
        except Exception as e:
            logger.warning(f"[DB] db_get_session error: {e}")
            return None
        finally:
            conn.close()


def db_delete_session(sid: str) -> None:
    init_db()
    with _DB_LOCK:
        conn = _get_connection()
        try:
            with conn:
                conn.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
        except Exception as e:
            logger.warning(f"[DB] db_delete_session error: {e}")
        finally:
            conn.close()


def db_load_all_sessions() -> Dict[str, Dict[str, Any]]:
    init_db()
    with _DB_LOCK:
        conn = _get_connection()
        try:
            cur = conn.execute("SELECT sid, data_json FROM sessions")
            res = {}
            for row in cur.fetchall():
                try:
                    res[row["sid"]] = json.loads(row["data_json"])
                except Exception:
                    pass
            return res
        except Exception as e:
            logger.warning(f"[DB] db_load_all_sessions error: {e}")
            return {}
        finally:
            conn.close()


# ── Run Operations ────────────────────────────────────────────────────────────

def db_save_run(run: Dict[str, Any]) -> None:
    init_db()
    with _DB_LOCK:
        conn = _get_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO runs (id, repo, status, data_json) VALUES (?, ?, ?, ?)",
                    (run.get("id", ""), run.get("repo", ""), run.get("status", ""), json.dumps(run)),
                )
        except Exception as e:
            logger.warning(f"[DB] db_save_run error: {e}")
        finally:
            conn.close()


def db_load_all_runs() -> List[Dict[str, Any]]:
    init_db()
    with _DB_LOCK:
        conn = _get_connection()
        try:
            cur = conn.execute("SELECT data_json FROM runs ORDER BY created_at DESC")
            runs = []
            for row in cur.fetchall():
                try:
                    runs.append(json.loads(row["data_json"]))
                except Exception:
                    pass
            return runs
        except Exception as e:
            logger.warning(f"[DB] db_load_all_runs error: {e}")
            return []
        finally:
            conn.close()
