import sys
import os
import re
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

def capture_baseline(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Captures the baseline state of the test suite before any patch is applied.
    Should be called in the IDLE state in LangGraph.
    """
    # Guard: only capture once
    if state.get("baseline_passing_tests") is not None:
        return state
        
    repo_full_name = state.get("repo_full_name", "")
    commit_sha = state.get("commit_sha", "")
    repo_url = f"https://github.com/{repo_full_name}" if repo_full_name else ""
    
    # 1. Run sandbox with NO patch
    sandbox_result = run_sandbox(repo_url, commit_sha, patch_diff=None)
    output = sandbox_result.get("output", "")
    
    # 2. Parse pytest output
    passing_tests = set()
    failing_tests = set()
    
    # Regex: test_path followed by whitespace and PASSED/FAILED
    pattern = r"(\S+)\s+(PASSED|FAILED)"
    for match in re.finditer(pattern, output):
        test_path = match.group(1)
        status = match.group(2)
        if status == "PASSED":
            passing_tests.add(test_path)
        elif status == "FAILED":
            failing_tests.add(test_path)
            
    # Convert to lists for JSON compatibility in LangGraph state
    state["baseline_passing_tests"] = list(passing_tests)
    state["baseline_failing_tests"] = list(failing_tests)
    
    # 3. Log results
    print(f"BASELINE CAPTURED — {len(passing_tests)} passing, {len(failing_tests)} failing")
    
    return state
