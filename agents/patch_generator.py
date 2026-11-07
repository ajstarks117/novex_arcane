import os
import difflib
import logging
from typing import Dict, Any
from agents.llm_client import call_llm

logger = logging.getLogger(__name__)

def generate_patch(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reads the failing file, queries the LLM for a corrected version,
    and computes a unified diff to be applied as a patch.
    """
    failing_file = state.get('failing_file', '')
    
    if not failing_file:
        logger.warning("[PatchGenerator] No failing_file found in state.")
        return {**state, "patch_diff": "", "retry_count": state.get("retry_count", 0) + 1}
        
    # Read the actual file content (mocking if not found for testing)
    original_content = ""
    try:
        # In the real flow, this would read from the Docker sandbox path
        if os.path.exists(failing_file):
            with open(failing_file, 'r', encoding='utf-8') as f:
                original_content = f.read()
        else:
            logger.warning(f"[PatchGenerator] File {failing_file} not found locally. Using mock content.")
            original_content = "def authenticate(user, password):\n    return False\n"
    except Exception as e:
        logger.error(f"[PatchGenerator] Error reading file: {e}")
        return {**state, "patch_diff": "", "retry_count": state.get("retry_count", 0) + 1}

    system_prompt = (
        "You are an expert developer. Your task is to fix a failing test by providing the corrected file content. "
        "You must return ONLY the raw Python file content. Start with the first line of the file. End with the last line. "
        "No text before or after. Do not use markdown code fences."
    )
    
    prompt = (
        f"File to fix: {failing_file}\n"
        f"Original Content:\n{original_content}\n\n"
        f"Root Cause Summary: {state.get('root_cause_summary', 'Unknown')}\n"
        f"Suspected Function: {state.get('suspected_function', 'Unknown')}\n"
    )
    
    if state.get("bisect_intent_report"):
        prompt += f"\nGit Bisect Context:\n{state.get('bisect_intent_report')}\n"
        
    if state.get("cascade_report"):
        prompt += f"\nCascade Failure Context (Do NOT break these):\n{state.get('cascade_report')}\n"
        
        
    if state.get("fast_forward_patch") and state.get("patch_diff"):
        logger.info("[PatchGenerator] ⏩ ChromaDB Fast-Forward active! Bypassing LLM patch generation.")
        return {
            **state,
            "retry_count": state.get("retry_count", 0) + 1
        }
        
    logger.info(f"[PatchGenerator] Asking LLM for corrected code for {failing_file}...")
    
    patched_content = call_llm(prompt=prompt, system=system_prompt)
    
    # Clean markdown if LLM includes it
    patched_content = patched_content.strip()
    if patched_content.startswith("```python"):
        patched_content = patched_content[9:]
    elif patched_content.startswith("```"):
        patched_content = patched_content[3:]
    if patched_content.endswith("```"):
        patched_content = patched_content[:-3]
    patched_content = patched_content.strip() + "\n"
    if not original_content.endswith("\n"):
        original_content += "\n"
        
    # Compute unified diff
    logger.info("[PatchGenerator] Computing unified diff...")
    original_lines = original_content.splitlines(keepends=True)
    patched_lines = patched_content.splitlines(keepends=True)
    
    diff_generator = difflib.unified_diff(
        original_lines, 
        patched_lines, 
        fromfile=f"a/{failing_file}", 
        tofile=f"b/{failing_file}",
        n=3
    )
    
    patch_diff = "".join(diff_generator)
    
    if not patch_diff:
        logger.warning("[PatchGenerator] Computed diff is empty. No changes detected.")
        
    retry_count = state.get("retry_count", 0)
        
    return {
        **state,
        "patch_diff": patch_diff,
        "retry_count": retry_count + 1
    }
