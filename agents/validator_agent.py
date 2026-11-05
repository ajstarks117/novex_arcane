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
    
    current_retry = state.get("retry_count", 0)
    
    # 3. Handle timeout
    if output == "TIMEOUT" or exit_code == -1:
        tests_passed = False
        state["timeout"] = True
        state["retry_count"] = current_retry + 1
        print(f"VALIDATOR TIMEOUT — sandbox exceeded 120s")
        state["validator_summary"] = "Sandbox timed out after 120s."
    
    # 1. Handle PASS
    elif exit_code == 0:
        tests_passed = True
        state["retry_count"] = current_retry # Do not increment
        print(f"VALIDATOR PASS — {repo_full_name} @ {commit_sha[:7]} — exit 0")
        state["validator_summary"] = "All tests passed. No failures."
        
    # 2. Handle FAIL
    else:
        tests_passed = False
        state["retry_count"] = current_retry + 1
        print(f"VALIDATOR FAIL — {repo_full_name} @ {commit_sha[:7]} — exit {exit_code} — retry {state['retry_count']}")
        state["validator_summary"] = f"Tests failed with exit code {exit_code}. Retry {state['retry_count']}."
    
    # Update the state dict
    state["tests_passed"] = tests_passed
    state["test_output"] = output
    state["validator_exit_code"] = exit_code
        
    return state
