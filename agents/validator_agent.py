import sys
import os
from typing import Dict, Any

# Ensure we can import from the agents package
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.sandbox_runner import run_sandbox

def validate(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validator Agent: applies a patch, runs pytest, and returns a pass/fail verdict.
    Called by the LangGraph orchestrator.
    """
    repo_full_name = state.get("repo_full_name", "")
    commit_sha = state.get("commit_sha", "")
    patch_diff = state.get("patch_diff")
    
    # Construct the full repo URL
    repo_url = f"https://github.com/{repo_full_name}" if repo_full_name else ""
    
    # Call the sandbox runner
    sandbox_result = run_sandbox(repo_url, commit_sha, patch_diff)
    
    exit_code = sandbox_result.get("exit_code", 1)
    output = sandbox_result.get("output", "")
    
    # Pass rule: tests_passed = True ONLY if exit_code == 0
    tests_passed = (exit_code == 0)
    
    # Update the state dict
    state["tests_passed"] = tests_passed
    state["test_output"] = output
    state["validator_exit_code"] = exit_code
    
    # Handle retry count
    current_retry = state.get("retry_count", 0)
    if not tests_passed:
        state["retry_count"] = current_retry + 1
    else:
        # Ensure retry_count exists even on pass, without incrementing
        state["retry_count"] = current_retry
        
    return state
