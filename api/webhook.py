import os
import hmac
import hashlib
import asyncio
import logging
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()
logger = logging.getLogger(__name__)

# Module-level asyncio queue (maxsize=10)
event_queue = asyncio.Queue(maxsize=10)

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
        raise HTTPException(status_code=403, detail="Invalid signature")
        
    # 3. Parse payload and extract fields
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
    # Safely extract requested fields
    repo = payload.get("repository", {})
    repo_full_name = repo.get("full_name")
    
    head_commit = payload.get("head_commit", {})
    commit_sha = head_commit.get("id")
    
    check_run = payload.get("check_run", {})
    output = check_run.get("output", {})
    failure_log = output.get("text")
    
    # 4. Push event dict to asyncio queue
    event_dict = {
        "repo_full_name": repo_full_name,
        "commit_sha": commit_sha,
        "failure_log": failure_log
    }
    
    # 5. Log dropped events if the queue is full
    try:
        event_queue.put_nowait(event_dict)
        logger.info(f"Queued webhook event: {repo_full_name} ({commit_sha})")
    except asyncio.QueueFull:
        logger.warning(f"Queue is full. Dropped webhook event for {repo_full_name} ({commit_sha})")
        
    return {"status": "received"}
