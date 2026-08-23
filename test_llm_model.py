import os
import pytest
from llm_client import LLMClient

def test_model_configuration():
    # Setup mock environment
    os.environ["LLM_MODE"] = "gemini"
    os.environ["GEMINI_API_KEY"] = "mock_key"
    os.environ["GEMINI_MODEL"] = "gemini-2.5-flash-lite"
    
    # Initialize client
    client = LLMClient()
    
    # Verify model is correctly assigned
    assert client.model_id == "gemini-2.5-flash-lite"
    
    # Cleanup
    del os.environ["GEMINI_API_KEY"]
    del os.environ["GEMINI_MODEL"]
