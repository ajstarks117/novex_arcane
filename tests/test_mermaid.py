import pytest
from unittest.mock import patch, MagicMock
from agents.mermaid_generator import validate_mermaid, generate_mermaid_diagram
import os

def test_validate_mermaid_valid():
    valid = "flowchart LR\n  A --> B"
    assert validate_mermaid(valid) == True

def test_validate_mermaid_invalid_missing_arrow():
    invalid = "flowchart LR\n  A - B"
    assert validate_mermaid(invalid) == False

def test_validate_mermaid_invalid_prefix():
    invalid = "Hello flowchart LR\n A --> B"
    assert validate_mermaid(invalid) == False

@patch("agents.mermaid_generator.os.getenv")
@patch("agents.mermaid_generator.anthropic.Anthropic")
def test_generate_mermaid_retries_on_hallucination(mock_anthropic_cls, mock_getenv):
    # Mock environment variable to bypass auth error
    mock_getenv.return_value = "fake_key"
    
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    
    # 1st call: returns bad mermaid (no flowchart/graph keyword). 
    # 2nd call: returns good mermaid.
    bad_response = MagicMock()
    bad_response.content = [MagicMock(text="Here is your diagram: A --> B")]
    
    good_response = MagicMock()
    good_response.content = [MagicMock(text="flowchart LR\n  A --> B")]
    
    mock_client.messages.create.side_effect = [bad_response, good_response]
    
    result = generate_mermaid_diagram("dummy_patch", "dummy_cause")
    
    # Verify client was called exactly twice because of the retry mechanism
    assert mock_client.messages.create.call_count == 2
    
    # Verify the result is wrapped inside mermaid fences
    assert result == "```mermaid\nflowchart LR\n  A --> B\n```"
