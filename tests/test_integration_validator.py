import time
from agents.validator_agent import validate

def test_integration_validator():
    print("Starting integration test for Validator Agent...")
    
    # Construct a fake state dict simulating what LangGraph will provide
    # We use 'main' which we know has passing tests
    state = {
        "repo_full_name": "aryanketkar-15/arcane-demo-repo",
        "commit_sha": "main",
        # We leave patch_diff as None because we know 'main' already passes. 
        # This acts as our "known-good" scenario to verify tests_passed = True.
        "patch_diff": None,
        "failing_test": "test_placeholder",
        "retry_count": 0
    }
    
    start_time = time.time()
    
    # Run the validator
    updated_state = validate(state)
    
    elapsed = time.time() - start_time
    
    # Assertions
    assert updated_state["tests_passed"] is True, "Expected tests_passed to be True for main branch"
    assert "All tests passed" in updated_state["validator_summary"], "Summary should reflect passing tests"
    assert updated_state["validator_exit_code"] == 0, "Exit code should be 0"
    
    # Print the full state returned
    print("\nINTEGRATION TEST PASSED")
    print(f"Time taken: {elapsed:.2f}s")
    print("\n--- Final State Dict ---")
    for k, v in updated_state.items():
        if k == "test_output":
            print(f"test_output: <truncated {len(v)} characters>")
        else:
            print(f"{k}: {v}")

if __name__ == "__main__":
    try:
        test_integration_validator()
    except AssertionError as e:
        print(f"TEST FAILED: {e}")
        exit(1)
