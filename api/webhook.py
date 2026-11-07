import os
import hmac
import hashlib
import asyncio
import logging
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()
logger = logging.getLogger(__name__)

# Module-level asyncio queue replaced by app.state.event_queue
# Removed here to avoid loop binding issues on reload


@router.post("/webhook")
async def receive_webhook(request: Request):
    """
    Single POST endpoint to receive GitHub Actions CI failure payloads.
    Validates HMAC signature and pushes parsed failure logs into the event queue.
    """
    # 2. Validate X-Hub-Signature-256 header using HMAC-SHA256
    secret_token = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not secret_token:
        # If secret is not configured, we should still handle the error cleanly
        logger.error("GITHUB_WEBHOOK_SECRET environment variable is not set")
        raise HTTPException(status_code=500, detail="Server webhook secret not configured")
        
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        raise HTTPException(status_code=403, detail="Missing X-Hub-Signature-256 header")
        
    body = await request.body()
    
    # Calculate expected HMAC
    mac = hmac.new(secret_token.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
    expected_signature = f"sha256={mac.hexdigest()}"
    
    # Securely compare signatures
    if not hmac.compare_digest(expected_signature, signature_header):
        logger.warning(f"Signature mismatch! GitHub sent: {signature_header}, Server expected: {expected_signature}. Did you type the Secret correctly in GitHub?")
        raise HTTPException(status_code=403, detail="Invalid signature")
        
    # 3. Parse payload and extract fields
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
    # Safely extract fields — handles both push events and check_run events
    repo = payload.get("repository", {})
    repo_full_name = repo.get("full_name")

    # Push event: head_commit.id | Check run event: check_run.head_sha
    head_commit = payload.get("head_commit", {})
    commit_sha = head_commit.get("id") or payload.get("check_run", {}).get("head_sha")

    # Failure log: from check_run output (CI events) or commit message (push events)
    check_run = payload.get("check_run", {})
    failure_log = (
        check_run.get("output", {}).get("text")
        or head_commit.get("message")
        or "No failure log provided"
    )

    event_type = request.headers.get("X-Github-Event", "unknown")
    logger.info(f"Received GitHub event: {event_type} for {repo_full_name}")

    # 4. Push event dict to asyncio queue
    event_dict = {
        "repo_full_name": repo_full_name,
        "commit_sha": commit_sha,
        "failure_log": failure_log,
    }

    # 5. Log dropped events if the queue is full
    try:
        request.app.state.event_queue.put_nowait(event_dict)
        logger.info(f"Queued webhook event: {repo_full_name} ({commit_sha})")
    except asyncio.QueueFull:
        logger.warning(f"Queue is full. Dropped event for {repo_full_name} ({commit_sha})")

    return {"status": "received"}
