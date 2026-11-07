import os
import anthropic
import httpx
import logging
import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def call_llm(prompt: str, system: str = '') -> str:
    """
    Calls Claude API with a fallback to local Ollama (llama3) if Claude fails
    or if the API key is missing.
    """
    
    # 1. Attempt Anthropic (Claude)
    if settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_API_KEY.strip():
        try:
            logger.info("Path used: Claude API (claude-3-5-sonnet-20240620)")
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            
            # Using the model specified in the prompt (noting that claude-3-5-sonnet-20240620 is a common valid one,
            # but using the user's specific string if provided. 
            # Prompt asked for: claude-sonnet-4-20250514)
            model_name = "claude-3-5-sonnet-20240620" # Defaulting to a known one for stability unless strictly required
            
            # The prompt requested: claude-sonnet-4-20250514
            # I will use that string as requested.
            model_name = "claude-sonnet-4-20250514" 

            message = client.messages.create(
                model=model_name,
                max_tokens=1024,
                system=system,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return message.content[0].text
            
        except Exception as e:
            logger.warning(f"Claude API call failed ({e}). Falling back to Ollama...")
    else:
        logger.info("Path used: Fallback (ANTHROPIC_API_KEY is empty)")

    # 2. Fallback to Ollama
    try:
        logger.info(f"Path used: Ollama (llama3) at {settings.OLLAMA_BASE_URL}")
        
        # Use httpx to call Ollama API
        url = f"{settings.OLLAMA_BASE_URL}/api/generate"
        payload = {
            "model": "llama3",
            "prompt": f"System: {system}\n\nUser: {prompt}" if system else prompt,
            "stream": False
        }
        
        response = httpx.post(url, json=payload, timeout=60.0)
        response.raise_for_status()
        
        result = response.json()
        return result.get("response", "")
        
    except Exception as e:
        logger.error(f"Ollama call failed: {e}")
        return f"Error: Both Claude and Ollama failed. Last error: {e}"
