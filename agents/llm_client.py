import os
import logging
import requests
from google import genai
from google.genai import types

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def call_ollama(prompt: str, system: str = '') -> str:
    """
    Fallback to local Ollama instance running llama3.1.
    Ollama must already be running: ollama run llama3.1
    """
    logger.info("Path used: Ollama Fallback (llama3.1)")
    try:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload = {
            "model": "llama3.1",
            "prompt": full_prompt,
            "stream": False
        }
        res = requests.post(f"{base_url}/api/generate", json=payload, timeout=120)
        res.raise_for_status()
        return res.json().get("response", "").strip()
    except Exception as e:
        logger.error(f"[LLM_Client] Ollama fallback also failed: {e}")
        return f"Error: Both Gemini and Ollama are unavailable: {e}"


def call_llm(prompt: str, system: str = '') -> str:
    """
    Primary LLM: Google Gemini 2.5 Flash.
    On 429 rate limit → falls back to Ollama llama3.1 (running locally).
    On any other error → returns error string.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if not api_key:
        logger.warning("[LLM_Client] GEMINI_API_KEY not found — routing to Ollama fallback.")
        return call_ollama(prompt, system)

    try:
        logger.info("Path used: Google Gemini (gemini-2.5-flash)")
        client = genai.Client(api_key=api_key)

        config = types.GenerateContentConfig(temperature=0.2)
        if system:
            config.system_instruction = system

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=config
        )
        return response.text.strip()

    except Exception as e:
        error_str = str(e).lower()
        if "429" in error_str or "quota" in error_str or "exhausted" in error_str:
            logger.warning("[LLM_Client] Gemini rate limit hit! Falling back to Ollama llama3.1...")
            return call_ollama(prompt, system)

        logger.error(f"[LLM_Client] Gemini API call failed: {e}")
        return f"Error: Gemini API call failed: {e}"
