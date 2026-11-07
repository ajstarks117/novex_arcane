import json
import logging
from typing import Dict, Any
from agents.llm_client import call_llm

logger = logging.getLogger(__name__)

def analyze(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyzes the failure log using an LLM to extract key details.
    Retries once with a stricter prompt if the LLM output is not valid JSON.
    """
    failure_log = state.get('failure_log', '')
    
    if not failure_log:
        logger.warning("[Analyst] No failure log provided in state.")
        return state
        
    # HACKATHON DEMO MODE: Detect "trigger" keyword and return successful dummy data
    if "trigger" in failure_log.lower():
        logger.info("[Analyst] Trigger keyword detected. Entering Demo Mode with sample data.")
        return {
            **state,
            "failing_test": "tests/test_api.py::test_user_auth",
            "failing_file": "api/auth.py",
            "failing_line": 42,
            "root_cause_summary": "Incorrect validation of JWT expiration timestamp leading to premature session termination.",
            "suspected_function": "validate_token"
        }

    system_prompt = (
        "You are an expert CI/CD failure analyst. Analyze the provided test failure log "
        "and extract the required information. You must respond ONLY with a valid JSON object. "
        "Do not include any preamble, explanations, or markdown fences (like ```json). "
        "The JSON object must have exactly these keys: "
        "\"failing_test\" (string), \"failing_file\" (string), \"failing_line\" (integer), "
        "\"root_cause_summary\" (string - max 2 sentences), \"suspected_function\" (string)."
    )

    prompt = f"Here is the failure log:\n\n{failure_log}"
    
    logger.info("[Analyst] Calling LLM to parse failure log...")
    response_text = call_llm(prompt=prompt, system=system_prompt)
    
    try:
        # First attempt to parse JSON
        parsed_data = json.loads(response_text.strip())
        logger.info("[Analyst] Successfully parsed JSON on first attempt.")
    except json.JSONDecodeError:
        logger.warning("[Analyst] Failed to parse JSON. Retrying with stricter prompt...")
        
        strict_system_prompt = (
            "You failed to return valid JSON previously. "
            "Return ONLY a raw JSON object. No text before or after it. No markdown code fences. "
            "The JSON object must have exactly these keys: "
            "\"failing_test\" (string), \"failing_file\" (string), \"failing_line\" (integer), "
            "\"root_cause_summary\" (string), \"suspected_function\" (string)."
        )
        
        response_text = call_llm(prompt=prompt, system=strict_system_prompt)
        
        try:
            # Second attempt
            # Try to strip any potential accidental markdown if the LLM still messed up
            clean_text = response_text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()
                
            parsed_data = json.loads(clean_text)
            logger.info("[Analyst] Successfully parsed JSON on retry.")
        except json.JSONDecodeError as e:
            logger.error(f"[Analyst] Failed to parse JSON on retry. Error: {e}")
            logger.error(f"Raw LLM response: {response_text}")
            # Return original state if we completely fail, to not break the pipeline
            return state

    # Update state with the extracted fields
    return {
        **state,
        "failing_test": parsed_data.get("failing_test", "unknown_test"),
        "failing_file": parsed_data.get("failing_file", "unknown_file"),
        "failing_line": parsed_data.get("failing_line", 0),
        "root_cause_summary": parsed_data.get("root_cause_summary", "Could not determine root cause."),
        "suspected_function": parsed_data.get("suspected_function", "unknown_function"),
    }
