"""GitHub OAuth login, per-user sessions and repository access."""
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.store import DATA_DIR, default_repo, now_iso, store
from api.db import db_delete_session, db_get_session, db_load_all_sessions, db_save_session

logger = logging.getLogger(__name__)
auth_router = APIRouter(prefix="/api")

SESSION_FILE = os.path.join(DATA_DIR, "sessions.json")
COOKIE = "arcane_session"
SCOPES = "repo admin:repo_hook read:user user:email"
_lock = threading.Lock()
_states: set[str] = set()


def _get_signing_key() -> bytes:
    key = (
        os.getenv("SECRET_KEY")
        or os.getenv("GITHUB_CLIENT_SECRET")
        or os.getenv("GITHUB_WEBHOOK_SECRET")
        or "arcane-session-secret-fallback-key"
    )
    return key.encode("utf-8")


def make_signed_session_token(sid: str, user: dict) -> str:
    """Creates a tamper-proof cryptographically signed cookie token containing minimal session data.
    Ensures that if the backend restarts or is redeployed on Render (ephemeral filesystem),
    the session can be seamlessly recovered without forcing the user to log in again."""
    payload = {
        "sid": sid,
        "login": user.get("login", ""),
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "avatar": user.get("avatar", ""),
        "token": user.get("token", ""),
        "createdAt": user.get("createdAt", ""),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    b64 = base64.urlsafe_b64encode(raw).decode("utf-8")
    sig = hmac.new(_get_signing_key(), b64.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{sid}.{b64}.{sig}"


def verify_signed_session_token(cookie_val: str) -> Optional[dict]:
    """Verifies HMAC signature of session token and extracts user data if valid."""
    if not cookie_val or "." not in cookie_val:
        return None
    parts = cookie_val.split(".")
    if len(parts) != 3:
        return None
    sid, b64, sig = parts
    expected_sig = hmac.new(_get_signing_key(), b64.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected_sig):
        logger.warning("[Auth] Invalid session signature")
        return None
    try:
        raw = base64.urlsafe_b64decode(b64.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        return data
    except Exception as e:
        logger.warning(f"[Auth] Could not decode session payload: {e}")
        return None


def oauth_configured() -> bool:
    return bool(os.getenv("GITHUB_CLIENT_ID") and os.getenv("GITHUB_CLIENT_SECRET"))


def app_url() -> str:
    return os.getenv("APP_URL", "http://localhost:5173").rstrip("/")


def _load() -> dict:
    # 1. Try loading from SQLite database
    try:
        db_sessions = db_load_all_sessions()
        if db_sessions:
            return db_sessions
    except Exception:
        pass

    # 2. Fall back to JSON file
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(sessions: dict) -> None:
    # 1. Save to JSON file
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = SESSION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sessions, f)
    os.replace(tmp, SESSION_FILE)
    try:
        os.chmod(SESSION_FILE, 0o600)
    except Exception:
        pass

    # 2. Also mirror to SQLite database for durability
    for sid, u in sessions.items():
        try:
            db_save_session(sid, u)
        except Exception:
            pass


def current_user(request: Request) -> Optional[dict]:
    """Returns the signed-in user (incl. token) or None.
    If the backend restarted and in-memory/file session was lost, recovers user
    from the cryptographically verified session cookie without logging the user out."""
    cookie_val = request.cookies.get(COOKIE)
    if not cookie_val:
        return None

    sid = cookie_val.split(".")[0] if "." in cookie_val else cookie_val

    with _lock:
        sessions = _load()
        user = sessions.get(sid) or db_get_session(sid)
        if user:
            return user

        # Attempt recovery from signed cookie token across container restart
        if "." in cookie_val:
            recovered = verify_signed_session_token(cookie_val)
            if recovered and recovered.get("login"):
                logger.info(f"[Auth] 🔄 Seamlessly restored session for '{recovered['login']}' across restart!")
                user = {
                    "login": recovered["login"],
                    "name": recovered.get("name") or recovered["login"],
                    "email": recovered.get("email") or "",
                    "avatar": recovered.get("avatar") or "",
                    "token": recovered.get("token") or "",
                    "createdAt": recovered.get("createdAt") or now_iso(),
                }
                sessions[sid] = user
                _save(sessions)
                return user

    return None


def require_user(request: Request) -> Optional[dict]:
    """Dependency: 401 when OAuth is enabled and nobody is signed in."""
    user = current_user(request)
    if user is None and oauth_configured():
        raise HTTPException(401, "Sign in with GitHub to continue.")
    return user


def public_user(user: Optional[dict]) -> Optional[dict]:
    if not user:
        return None
    return {k: user.get(k) for k in ("login", "name", "email", "avatar")}


def token_for_login(login: str) -> Optional[str]:
    with _lock:
        for u in _load().values():
            if u.get("login") == login:
                return u.get("token")
    return None


def token_for_repo(repo: str) -> Optional[str]:
    """Token of the user who watches `repo` (used for webhook-triggered runs)."""
    login = store.watched.get(repo)
    if login:
        tok = token_for_login(login)
        if tok:
            return tok
    owner = repo.split("/")[0] if "/" in repo else repo
    tok = token_for_login(owner)
    if tok:
        return tok
    with _lock:
        sessions = _load()
        for u in sessions.values():
            if u.get("token"):
                return u.get("token")
    return None


# ── OAuth flow ───────────────────────────────────────────────────────────────

@auth_router.get("/auth/config")
def auth_config():
    return {"oauth": oauth_configured()}


@auth_router.get("/auth/github/login")
def login():
    if not oauth_configured():
        raise HTTPException(503, "GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET are not set in .env")
    state = secrets.token_urlsafe(24)
    _states.add(state)
    q = urlencode(
        {
            "client_id": os.environ["GITHUB_CLIENT_ID"],
            "redirect_uri": f"{app_url()}/api/auth/github/callback",
            "scope": SCOPES,
            "state": state,
        }
    )
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{q}")


@auth_router.get("/auth/github/callback")
def callback(code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse(f"{app_url()}/?auth_error={error}")
    if state not in _states:
        return RedirectResponse(f"{app_url()}/?auth_error=invalid_state")
    _states.discard(state)
    try:
        tok = httpx.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": os.environ["GITHUB_CLIENT_ID"],
                "client_secret": os.environ["GITHUB_CLIENT_SECRET"],
                "code": code,
                "redirect_uri": f"{app_url()}/api/auth/github/callback",
            },
            headers={"Accept": "application/json"},
            timeout=15,
        ).json()
        token = tok.get("access_token")
        if not token:
            logger.warning(f"[Auth] token exchange failed: {tok.get('error')}")
            return RedirectResponse(f"{app_url()}/?auth_error={tok.get('error', 'token_exchange_failed')}")
        gh = httpx.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=15,
        ).json()
    except Exception as e:
        logger.error(f"[Auth] OAuth error: {e}")
        return RedirectResponse(f"{app_url()}/?auth_error=network")
    sid = secrets.token_urlsafe(32)
    user_record = {
        "login": gh.get("login"),
        "name": gh.get("name") or gh.get("login"),
        "email": gh.get("email") or "",
        "avatar": gh.get("avatar_url") or "",
        "token": token,
        "createdAt": now_iso(),
    }
    with _lock:
        sessions = _load()
        sessions[sid] = user_record
        _save(sessions)
    store.add_audit("Signed in with GitHub", "Workspace", gh.get("login", "unknown"))
    signed_cookie_val = make_signed_session_token(sid, user_record)
    resp = RedirectResponse(f"{app_url()}/")
    resp.set_cookie(COOKIE, signed_cookie_val, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 14, path="/")
    return resp


@auth_router.get("/me")
def me(request: Request):
    user = current_user(request)
    if user is None and oauth_configured():
        raise HTTPException(401, "Not signed in")
    pub = public_user(user) or {"login": "local", "name": "Local user", "email": "", "avatar": ""}
    pub["workspace"] = store.settings.get("workspace", "Team Bahadur")
    pub["oauth"] = oauth_configured()
    return pub


@auth_router.post("/auth/logout")
def logout(request: Request, response: Response):
    cookie_val = request.cookies.get(COOKIE)
    if cookie_val:
        sid = cookie_val.split(".")[0] if "." in cookie_val else cookie_val
        with _lock:
            s = _load()
            s.pop(sid, None)
            _save(s)
            try:
                db_delete_session(sid)
            except Exception:
                pass
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


# ── repositories ─────────────────────────────────────────────────────────────

@auth_router.get("/github/repos")
def my_repos(user=Depends(require_user)):
    token = (user or {}).get("token") or os.getenv("GITHUB_PAT")
    if not token:
        raise HTTPException(400, "No GitHub token available.")
    try:
        r = httpx.get(
            "https://api.github.com/user/repos",
            params={"per_page": 100, "sort": "pushed", "affiliation": "owner,collaborator,organization_member"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=20,
        )
        if r.status_code == 401:
            raise HTTPException(401, "GitHub rejected the token — sign in again.")
        r.raise_for_status()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"GitHub request failed: {e}")
    return {
        "repos": [
            {
                "name": x["full_name"],
                "private": x["private"],
                "defaultBranch": x["default_branch"],
                "pushedAt": x["pushed_at"],
                "watched": x["full_name"] in store.watched,
                "canAdmin": bool((x.get("permissions") or {}).get("admin")),
            }
            for x in r.json()
        ]
    }


class WatchBody(BaseModel):
    repo: str
    webhook: bool = True


@auth_router.post("/github/watch")
def watch_repo(body: WatchBody, user=Depends(require_user)):
    login_name = (user or {}).get("login", "local")
    token = (user or {}).get("token") or os.getenv("GITHUB_PAT")
    if "/" not in body.repo:
        raise HTTPException(400, "Repository must look like owner/name.")
    hook_msg = "Webhook not created."
    if body.webhook:
        public = os.getenv("PUBLIC_URL", "").rstrip("/")
        secret = os.getenv("GITHUB_WEBHOOK_SECRET")
        if not public:
            hook_msg = "Watching, but no webhook yet: set PUBLIC_URL in .env (your tunnel URL) to create it automatically."
        elif not (token and secret):
            hook_msg = "Watching, but the webhook needs a token and GITHUB_WEBHOOK_SECRET."
        else:
            try:
                r = httpx.post(
                    f"https://api.github.com/repos/{body.repo}/hooks",
                    json={
                        "name": "web",
                        "active": True,
                        "events": ["push"],
                        "config": {"url": f"{public}/webhook", "content_type": "json", "secret": secret},
                    },
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                    timeout=20,
                )
                if r.status_code in (200, 201):
                    hook_msg = "Webhook created."
                elif r.status_code == 422:
                    hook_msg = "Webhook already exists."
                else:
                    hook_msg = f"GitHub refused the webhook ({r.status_code}): you need admin rights on the repo."
            except Exception as e:
                hook_msg = f"Webhook request failed: {e}"
    store.watched[body.repo] = login_name
    names = [r["name"] for r in store.settings.get("repositories", [])]
    if body.repo not in names:
        store.settings.setdefault("repositories", []).append(default_repo(body.repo))
    store.add_audit("Started watching a repository", body.repo, login_name)
    store.save()
    return {"ok": True, "message": hook_msg}


@auth_router.delete("/github/watch")
def unwatch_repo(repo: str, user=Depends(require_user)):
    store.watched.pop(repo, None)
    store.settings["repositories"] = [r for r in store.settings.get("repositories", []) if r["name"] != repo]
    store.add_audit("Stopped watching a repository", repo, (user or {}).get("login", "local"))
    store.save()
    return {"ok": True}
