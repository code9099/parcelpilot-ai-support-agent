import os
os.environ["LLM_MODE"] = "mock"

import time
import pytest
from fastapi.testclient import TestClient
from app import app, orchestrator
from orchestrator import PendingAction
import db
import ingest

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    db.init_db()
    ingest.ingest()
    os.environ["LLM_MODE"] = "mock"
    # Reset pending actions
    orchestrator.pending_actions = {}


def test_context_cannot_override_session():
    """Prove malicious client context cannot override server session/account info."""
    payload = {
        "profile_id": "NORTHSTAR",
        "user_text": "status",
        "context_links": [
            # Attempting to inject account_id or role into context_links
            {"context_order_id": "ORD-1001", "account_id": "ACCT-002", "role": "admin"}
        ]
    }
    
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    session_used = data["_trace"]["session"]
    
    # Server derived state must take precedence
    assert session_used["account_id"] == "ACCT-001"
    assert session_used["role"] == "customer"
    
    # Verify the injected fields were stripped from context_links
    dc = data["_trace"]["decision_context"]
    # We can check that the explicit context link only contains the order id fact
    found_order_fact = False
    for f in dc["applicable_facts"]:
        if f["type"] == "EXPLICIT_CONTEXT_LINK":
            assert "ORD-1001" in f["fact"]
            assert "ACCT-002" not in f["fact"]
            assert "admin" not in f["fact"]
            found_order_fact = True
    assert found_order_fact


def test_invalid_profile_rejected():
    """Client cannot arbitrarily choose an account identity."""
    payload = {
        "profile_id": "HACKER",
        "user_text": "status"
    }
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 400


def test_cross_account_confirmation():
    """Test ACCT-002 cannot confirm ACCT-001's action via API."""
    orchestrator.pending_actions["req-123"] = PendingAction(
        request_id="req-123",
        account_id="ACCT-001",
        action_type="escalate",
        payload={},
        expires_at=time.time() + 300,
        status="pending_confirmation"
    )
    
    payload = {
        "profile_id": "LUMENWORKS", # This is ACCT-002
        "request_id": "req-123"
    }
    response = client.post("/api/action/confirm", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "execution_failed"
    assert "cross-account" in data["error"].lower() or "unauthorized" in data["error"].lower()


def test_expired_duplicate_action():
    """Test expired and duplicate confirmations via API."""
    # Setup action that expires immediately
    orchestrator.pending_actions["req-exp"] = PendingAction(
        request_id="req-exp",
        account_id="ACCT-001",
        action_type="escalate",
        payload={},
        expires_at=time.time() - 10,
        status="pending_confirmation"
    )
    
    # Confirm expired
    response = client.post("/api/action/confirm", json={"profile_id": "NORTHSTAR", "request_id": "req-exp"})
    assert response.json()["status"] == "expired"
    
    # Setup valid action
    orchestrator.pending_actions["req-dup"] = PendingAction(
        request_id="req-dup",
        account_id="ACCT-001",
        action_type="escalate",
        payload={},
        expires_at=time.time() + 300,
        status="pending_confirmation"
    )
    
    # First confirm
    response = client.post("/api/action/confirm", json={"profile_id": "NORTHSTAR", "request_id": "req-dup"})
    assert response.json()["status"] == "executed"
    
    # Duplicate confirm
    response2 = client.post("/api/action/confirm", json={"profile_id": "NORTHSTAR", "request_id": "req-dup"})
    assert response2.json()["status"] == "already_executed"


def test_missing_api_key():
    """Test fallback when GEMINI_API_KEY is unavailable."""
    # Enforce real gemini mode but remove key
    os.environ["LLM_MODE"] = "gemini"
    old_key = os.environ.get("GEMINI_API_KEY")
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
        
    try:
        from llm_client import LLMClient
        with pytest.raises(ValueError, match="GEMINI_API_KEY is required"):
            client = LLMClient()
    finally:
        if old_key is not None:
            os.environ["GEMINI_API_KEY"] = old_key
            
            
# (The rest of the LLM isolation edge cases like confirm_action exclusion, unknown tools, 
# and malformed outputs are already rigorously tested in test_orchestrator.py, but we ensure 
# they pass implicitly here via the mock logic or the existing test suite).
