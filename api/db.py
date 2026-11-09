"""Database storage backend for ARCANE session, run, and settings persistence.

Storage Architecture & Deployment Environment Limitations:
===========================================================
1. Local SQLite (Default / Instance-Local Storage):
   - Stores data in a local SQLite file (default: `data/arcane.db` or `ARCANE_DB_PATH`).
   - IMPORTANT LIMITATION: On cloud platforms with ephemeral containers (such as Render's
     free web tier), local filesystem modifications do NOT persist across container replacement,
     service redeployments, or scale-to-zero restarts.
   - To retain SQLite data across container replacements on Render, a Render Persistent Disk
     must be attached and `ARCANE_DB_PATH` set to the mount path (e.g. `/var/data/arcane.db`).

2. PostgreSQL (Truly Persistent Cross-Container Storage):
   - Supported when `DATABASE_URL` is set to a PostgreSQL URI (`postgresql://` or `postgres://`).
   - Requires a PostgreSQL client library (`psycopg` or `psycopg2`).
   - If `DATABASE_URL` is set to PostgreSQL but no driver is installed in the environment,
     ARCANE logs a prominent warning and safely uses instance-local SQLite, NEVER passing
     the `postgres://` connection string to `sqlite3`.
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
_PG_AVAILABLE: Optional[bool] = None
_PG_CONN = None


def is_postgres_configured() -> bool:
    """Returns True if DATABASE_URL specifies a PostgreSQL database."""
    url = os.getenv("DATABASE_URL", "").strip()
    return url.startswith("postgresql://") or url.startswith("postgres://")


def is_postgres_driver_available() -> bool:
    """Checks whether psycopg or psycopg2 is installed."""
    global _PG_AVAILABLE
    if _PG_AVAILABLE is not None:
        return _PG_AVAILABLE

    try:
        import psycopg  # psycopg v3
        _PG_AVAILABLE = True
        return True
    except ImportError:
        pass

    try:
        import psycopg2  # psycopg v2
        _PG_AVAILABLE = True
        return True
    except ImportError:
        pass

    _PG_AVAILABLE = False
    return False


def get_sqlite_path() -> str:
    """Returns the local SQLite database file path.
    Guarantees that a postgres:// URL is never returned for SQLite operations."""
    global _DB_PATH
    if _DB_PATH:
        return _DB_PATH

    custom_url = os.getenv("ARCANE_DB_PATH") or os.getenv("DATABASE_URL", "")
    if custom_url and (custom_url.startswith("sqlite:///") or custom_url.endswith(".db")):
        path = custom_url.replace("sqlite:///", "")
    else:
        # Default local SQLite file
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        os.makedirs(data_dir, exist_ok=True)
        path = os.path.join(data_dir, "arcane.db")

    _DB_PATH = path
    return _DB_PATH


def _get_sqlite_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_sqlite_path(), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _get_postgres_connection():
    """Returns a PostgreSQL connection if driver is available."""
    url = os.getenv("DATABASE_URL", "").strip()
    try:
        import psycopg
        return psycopg.connect(url)
    except ImportError:
        pass

    try:
        import psycopg2
        return psycopg2.connect(url)
    except Exception as e:
        logger.warning(f"[DB] PostgreSQL connection failed: {e}")
        return None


def init_db() -> None:
    """Initializes schema for sessions, runs, and settings.
    Dispatches to PostgreSQL if configured and driver available, otherwise SQLite."""
    with _DB_LOCK:
        if is_postgres_configured():
            if is_postgres_driver_available():
                conn = _get_postgres_connection()
                if conn:
                    try:
                        with conn:
                            with conn.cursor() as cur:
                                cur.execute("""
                                    CREATE TABLE IF NOT EXISTS sessions (
                                        sid VARCHAR(255) PRIMARY KEY,
                                        login VARCHAR(255),
                                        data_json TEXT NOT NULL,
                                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                    );
                                """)
                                cur.execute("""
                                    CREATE TABLE IF NOT EXISTS runs (
                                        id VARCHAR(255) PRIMARY KEY,
                                        repo VARCHAR(255),
                                        status VARCHAR(64),
                                        data_json TEXT NOT NULL,
                                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                    );
                                """)
                                cur.execute("""
                                    CREATE TABLE IF NOT EXISTS settings (
                                        key VARCHAR(255) PRIMARY KEY,
                                        data_json TEXT NOT NULL,
                                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                    );
                                """)
                        logger.info("[DB] Initialized persistent PostgreSQL storage.")
                        return
                    except Exception as e:
                        logger.warning(f"[DB] PostgreSQL init failed: {e}")
                    finally:
                        conn.close()
            else:
                logger.warning(
                    "[DB] DATABASE_URL is set to PostgreSQL, but neither 'psycopg' nor 'psycopg2' "
                    "is installed. Falling back to instance-local SQLite. Note that data will be "
                    "stored locally and will reset on container replacement unless a persistent disk is attached."
                )

        # Fallback / Default: SQLite
        conn = _get_sqlite_connection()
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
        if is_postgres_configured() and is_postgres_driver_available():
            conn = _get_postgres_connection()
            if conn:
                try:
                    with conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO sessions (sid, login, data_json, updated_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP) "
                                "ON CONFLICT (sid) DO UPDATE SET login = EXCLUDED.login, data_json = EXCLUDED.data_json, updated_at = CURRENT_TIMESTAMP",
                                (sid, user.get("login", ""), json.dumps(user)),
                            )
                    return
                except Exception as e:
                    logger.warning(f"[DB] PostgreSQL save_session failed: {e}")
                finally:
                    conn.close()

        # SQLite
        conn = _get_sqlite_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO sessions (sid, login, data_json, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (sid, user.get("login", ""), json.dumps(user)),
                )
        except Exception as e:
            logger.warning(f"[DB] SQLite save_session error: {e}")
        finally:
            conn.close()


def db_get_session(sid: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _DB_LOCK:
        if is_postgres_configured() and is_postgres_driver_available():
            conn = _get_postgres_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT data_json FROM sessions WHERE sid = %s", (sid,))
                        row = cur.fetchone()
                        if row:
                            return json.loads(row[0])
                    return None
                except Exception as e:
                    logger.warning(f"[DB] PostgreSQL get_session failed: {e}")
                finally:
                    conn.close()

        # SQLite
        conn = _get_sqlite_connection()
        try:
            cur = conn.execute("SELECT data_json FROM sessions WHERE sid = ?", (sid,))
            row = cur.fetchone()
            if row:
                return json.loads(row["data_json"])
            return None
        except Exception as e:
            logger.warning(f"[DB] SQLite get_session error: {e}")
            return None
        finally:
            conn.close()


def db_delete_session(sid: str) -> None:
    init_db()
    with _DB_LOCK:
        if is_postgres_configured() and is_postgres_driver_available():
            conn = _get_postgres_connection()
            if conn:
                try:
                    with conn:
                        with conn.cursor() as cur:
                            cur.execute("DELETE FROM sessions WHERE sid = %s", (sid,))
                    return
                except Exception as e:
                    logger.warning(f"[DB] PostgreSQL delete_session failed: {e}")
                finally:
                    conn.close()

        # SQLite
        conn = _get_sqlite_connection()
        try:
            with conn:
                conn.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
        except Exception as e:
            logger.warning(f"[DB] SQLite delete_session error: {e}")
        finally:
            conn.close()


def db_load_all_sessions() -> Dict[str, Dict[str, Any]]:
    init_db()
    with _DB_LOCK:
        if is_postgres_configured() and is_postgres_driver_available():
            conn = _get_postgres_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT sid, data_json FROM sessions")
                        res = {}
                        for row in cur.fetchall():
                            try:
                                res[row[0]] = json.loads(row[1])
                            except Exception:
                                pass
                        return res
                except Exception as e:
                    logger.warning(f"[DB] PostgreSQL load_all_sessions failed: {e}")
                finally:
                    conn.close()

        # SQLite
        conn = _get_sqlite_connection()
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
            logger.warning(f"[DB] SQLite load_all_sessions error: {e}")
            return {}
        finally:
            conn.close()


# ── Run Operations ────────────────────────────────────────────────────────────

def db_save_run(run: Dict[str, Any]) -> None:
    init_db()
    with _DB_LOCK:
        if is_postgres_configured() and is_postgres_driver_available():
            conn = _get_postgres_connection()
            if conn:
                try:
                    with conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO runs (id, repo, status, data_json) VALUES (%s, %s, %s, %s) "
                                "ON CONFLICT (id) DO UPDATE SET repo = EXCLUDED.repo, status = EXCLUDED.status, data_json = EXCLUDED.data_json",
                                (run.get("id", ""), run.get("repo", ""), run.get("status", ""), json.dumps(run)),
                            )
                    return
                except Exception as e:
                    logger.warning(f"[DB] PostgreSQL save_run failed: {e}")
                finally:
                    conn.close()

        # SQLite
        conn = _get_sqlite_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO runs (id, repo, status, data_json) VALUES (?, ?, ?, ?)",
                    (run.get("id", ""), run.get("repo", ""), run.get("status", ""), json.dumps(run)),
                )
        except Exception as e:
            logger.warning(f"[DB] SQLite save_run error: {e}")
        finally:
            conn.close()


def db_load_all_runs() -> List[Dict[str, Any]]:
    init_db()
    with _DB_LOCK:
        if is_postgres_configured() and is_postgres_driver_available():
            conn = _get_postgres_connection()
            if conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT data_json FROM runs ORDER BY created_at DESC")
                        runs = []
                        for row in cur.fetchall():
                            try:
                                runs.append(json.loads(row[0]))
                            except Exception:
                                pass
                        return runs
                except Exception as e:
                    logger.warning(f"[DB] PostgreSQL load_all_runs failed: {e}")
                finally:
                    conn.close()

        # SQLite
        conn = _get_sqlite_connection()
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
            logger.warning(f"[DB] SQLite load_all_runs error: {e}")
            return []
        finally:
            conn.close()
