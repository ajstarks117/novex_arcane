import unittest
from unittest.mock import patch
from agents.validator_agent import validate

class TestValidatorAgent(unittest.TestCase):
    
    def setUp(self):
        self.base_state = {
            "repo_full_name": "teambahadur/arcane-demo",
            "commit_sha": "abcdef1234567890",
            "patch_diff": "fake_diff",
            "retry_count": 0
        }

    @patch('agents.validator_agent.run_sandbox')
    def test_validator_pass(self, mock_run_sandbox):
        # Mock successful sandbox run
        mock_run_sandbox.return_value = {
            "passed": True,
            "output": "10 passed",
            "exit_code": 0
        }
        
        new_state = validate(self.base_state.copy())
        
        self.assertTrue(new_state["tests_passed"])
        self.assertEqual(new_state["retry_count"], 0) # No increment
        self.assertFalse(new_state.get("timeout", False))
        self.assertEqual(new_state["validator_summary"], "All tests passed. No failures.")
        
    @patch('agents.validator_agent.run_sandbox')
    def test_validator_fail(self, mock_run_sandbox):
        # Mock failed sandbox run
        mock_run_sandbox.return_value = {
            "passed": False,
            "output": "1 failed",
            "exit_code": 1
        }
        
        new_state = validate(self.base_state.copy())
        
        self.assertFalse(new_state["tests_passed"])
        self.assertEqual(new_state["retry_count"], 1) # Incremented
        self.assertFalse(new_state.get("timeout", False))
        self.assertTrue("Retry 1" in new_state["validator_summary"])
        
    @patch('agents.validator_agent.run_sandbox')
    def test_validator_timeout(self, mock_run_sandbox):
        # Mock sandbox timeout
        mock_run_sandbox.return_value = {
            "passed": False,
            "output": "TIMEOUT",
            "exit_code": -1
        }
        
        new_state = validate(self.base_state.copy())
        
        self.assertFalse(new_state["tests_passed"])
        self.assertEqual(new_state["retry_count"], 1) # Incremented
        self.assertTrue(new_state["timeout"])
        self.assertEqual(new_state["validator_summary"], "Sandbox timed out after 120s.")

if __name__ == '__main__':
    unittest.main()
