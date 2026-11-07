import asyncio
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load environment variables before other imports
load_dotenv()

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.webhook import router as webhook_router, event_queue
from agents.workflow import graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Shared pipeline state — LangGraph updates this at each node transition ──
pipeline_status = {
    "current_state": "IDLE",
    "last_event": None,
    "agents": {
        "analyst":         "idle",
        "bisect":          "idle",
        "patch_generator": "idle",
        "validator":       "idle",
        "pr_agent":        "idle",
    },
    "pr_url":  None,
    "error":   None,
}

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

        # Stamp last_event so the dashboard can show it
        pipeline_status["last_event"] = {
            "repo":         event.get("repo_full_name"),
            "sha":          event.get("commit_sha"),
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        }
        pipeline_status["current_state"] = "ANALYZING"

        try:
            # Build initial state from webhook payload
            initial_state = {
                "repo_full_name": event.get("repo_full_name", ""),
                "commit_sha":     event.get("commit_sha", ""),
                "failure_log":    event.get("failure_log", ""),
                # Placeholder — AST / LLM layers will populate these in Phase 2
                "patch_diff":     event.get("failure_log", "# placeholder patch"),
                "failing_test":   "unknown_test",
                "retry_count":    0,
            }

            # Run the LangGraph workflow
            result = graph.invoke(initial_state)

            if result.get("pr_url"):
                pipeline_status["pr_url"] = result["pr_url"]
                pipeline_status["current_state"] = "DONE"
                logger.info(f"[Consumer] ✅ PR created: {result['pr_url']}")
            elif result.get("error"):
                pipeline_status["current_state"] = "ESCALATED"
                pipeline_status["error"] = result["error"]
                logger.warning(f"[Consumer] ⚠️  Workflow ended with error: {result['error']}")
            else:
                pipeline_status["current_state"] = "DONE"
                logger.info(f"[Consumer] Workflow completed: {result}")

        except Exception as e:
            logger.error(f"[Consumer] Unhandled error processing event: {e}")
            pipeline_status["current_state"] = "ESCALATED"
            pipeline_status["error"] = str(e)
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

# ── CORS — allow the React dev server (port 5173) to talk to FastAPI ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/api/status")
async def get_status():
    """Returns the current LangGraph pipeline telemetry for the dashboard."""
    return pipeline_status

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
