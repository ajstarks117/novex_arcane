import os
import logging
from dotenv import load_dotenv
import anthropic

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

def validate_mermaid(mermaid_str: str) -> bool:
    """
    Returns True only if string starts with "flowchart" or "graph"
    AND contains at least one arrow (-->)
    Logs a warning and returns False otherwise
    """
    # Clean string to check prefix accurately
    cleaned = mermaid_str.strip().lower()
    
    # If the LLM mistakenly includes backticks, trim them for validation
    if cleaned.startswith("```mermaid"):
        cleaned = cleaned[len("```mermaid"):].strip()
        
    if not (cleaned.startswith("flowchart") or cleaned.startswith("graph")):
        logger.warning(f"Mermaid validation failed: Does not start with 'flowchart' or 'graph'. String starts with: {cleaned[:20]}")
        return False
        
    if "-->" not in mermaid_str:
        logger.warning("Mermaid validation failed: Missing arrow (-->)")
        return False
        
    return True

def generate_mermaid_diagram(patch_diff: str, root_cause: str) -> str:
    """
    Calls Anthropic API to generate a Mermaid.js flowchart.
    Retries once with a stricter prompt if validation fails.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not found in environment.")
        return ""
        
    client = anthropic.Anthropic(api_key=api_key)
    model_name = "claude-sonnet-4-20250514"
    
    system_prompt = (
        "You are a code diagram expert. Given a unified diff and "
        "root cause, generate a Mermaid.js flowchart comparing the "
        "old execution path (before the fix) with the new execution "
        "path (after the fix). Return ONLY valid Mermaid syntax. "
        "Start with: flowchart LR. No explanations, no markdown "
        "fences, just the raw Mermaid code."
    )
    
    user_prompt = f"Root Cause: {root_cause}\n\nPatch Diff:\n{patch_diff}"
    
    try:
        response = client.messages.create(
            model=model_name,
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        mermaid_raw = response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Anthropic API call failed: {e}")
        return ""
        
    if not validate_mermaid(mermaid_raw):
        logger.warning("Initial mermaid output was invalid. Retrying with stricter prompt...")
        
        stricter_prompt = system_prompt + (
            " FAILURE: Your previous output was invalid. YOU MUST RETURN ONLY THE RAW MERMAID CODE. "
            "Example format:\nflowchart LR\n  A[Start] --> B[End]"
        )
        
        try:
            response = client.messages.create(
                model=model_name,
                max_tokens=1000,
                system=stricter_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )
            mermaid_raw = response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Anthropic API retry failed: {e}")
            return ""
            
        if not validate_mermaid(mermaid_raw):
            logger.error("Retry failed: Output still invalid.")
            return ""
            
    # Wrap result in triple backtick mermaid fence
    return f"```mermaid\n{mermaid_raw}\n```"
