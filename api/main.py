import logging
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables before other imports
load_dotenv()

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from api.webhook import router as webhook_router, event_queue
from agents.orchestrator import run_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Shared pipeline state — LangGraph updates this at each node transition ──
pipeline_status = {
    "current_state": "IDLE",
    "last_event": None,
    "agents": {
        "analyst":        "idle",
        "bisect":         "idle",
        "patch_generator":"idle",
        "validator":      "idle",
        "pr_agent":       "idle",
    },
    "pr_url":  None,
    "error":   None,
}

async def process_queue():
    """Background task to consume events from the webhook queue."""
    logger.info("Starting background queue consumer")
    while True:
        try:
            event = await event_queue.get()
            logger.info(f"Dequeued event for processing: {event}")

            # Stamp last_event so the dashboard can show it
            pipeline_status["last_event"] = {
                "repo":         event.get("repo_full_name"),
                "sha":          event.get("commit_sha"),
                "triggered_at": datetime.now(timezone.utc).isoformat(),
            }
            pipeline_status["current_state"] = "ANALYZING"

            await run_pipeline(event)
            event_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error processing event: {e}")
            pipeline_status["current_state"] = "ESCALATED"
            pipeline_status["error"] = str(e)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(process_queue())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

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
