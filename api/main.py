import logging
from dotenv import load_dotenv

# Load environment variables before other imports
load_dotenv()

import uvicorn
from fastapi import FastAPI
from api.webhook import router as webhook_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="ARCANE API")

# Register the webhook endpoints
app.include_router(webhook_router)

@app.get("/health")
async def health_check():
    """Health check endpoint returning status ok."""
    return {"status": "ok"}

if __name__ == "__main__":
    # Run the FastAPI app using uvicorn on port 8000
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
