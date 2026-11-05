import asyncio
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load environment variables before other imports
load_dotenv()

import uvicorn
from fastapi import FastAPI
from api.webhook import router as webhook_router, event_queue
from agents.workflow import graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Async consumer: drains the webhook queue → runs LangGraph ────────────────

async def process_events():
    """
    Long-running task that pulls events from the webhook queue
    and feeds each one into the compiled LangGraph workflow.
    """
    logger.info("[Consumer] Event processor started — waiting for webhook events")
    while True:
        event = await event_queue.get()
        logger.info(
            f"[Consumer] Processing event for "
            f"{event.get('repo_full_name')} ({event.get('commit_sha', '?')[:7]})"
        )
        try:
            # Build initial state from webhook payload
            initial_state = {
                "repo_full_name": event.get("repo_full_name", ""),
                "commit_sha": event.get("commit_sha", ""),
                "failure_log": event.get("failure_log", ""),
                # Placeholder — AST / LLM layers will populate these in Phase 2
                "patch_diff": event.get("failure_log", "# placeholder patch"),
                "failing_test": "unknown_test",
                "retry_count": 0,
            }

            # Run the LangGraph workflow
            result = graph.invoke(initial_state)

            if result.get("pr_url"):
                logger.info(f"[Consumer] ✅ PR created: {result['pr_url']}")
            elif result.get("error"):
                logger.warning(f"[Consumer] ⚠️  Workflow ended with error: {result['error']}")
            else:
                logger.info(f"[Consumer] Workflow completed: {result}")

        except Exception as e:
            logger.error(f"[Consumer] Unhandled error processing event: {e}")
        finally:
            event_queue.task_done()


# ── App lifecycle ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background consumer on startup, cancel on shutdown."""
    task = asyncio.create_task(process_events())
    logger.info("[Lifespan] Background event processor launched")
    yield
    task.cancel()
    logger.info("[Lifespan] Background event processor cancelled")


app = FastAPI(title="ARCANE API", lifespan=lifespan)

# Register the webhook endpoints
app.include_router(webhook_router)


@app.get("/health")
async def health_check():
    """Health check endpoint returning status ok."""
    return {"status": "ok"}


if __name__ == "__main__":
    # Run the FastAPI app using uvicorn on port 8000
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
