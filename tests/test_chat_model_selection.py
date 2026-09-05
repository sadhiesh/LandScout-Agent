"""Test /chat endpoint model selection validation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Assuming a test fixture exists or we create one here
# This test verifies the validation logic without starting real agents


def test_chat_validates_unknown_provider():
    """POST /chat with unknown provider returns 400."""
    from api.main import app
    
    client = TestClient(app)
    
    response = client.post(
        "/chat",
        json={
            "session_id": "test-session",
            "message": "test",
            "llm_provider": "nonexistent",
            "llm_model": "fake-model",
        },
        headers={"X-Run-ID": "test-run"},
    )
    
    assert response.status_code == 400
    assert "Unknown provider" in response.json()["detail"]


def test_chat_validates_unknown_model():
    """POST /chat with unknown model returns 400."""
    from api.main import app
    
    client = TestClient(app)
    
    response = client.post(
        "/chat",
        json={
            "session_id": "test-session",
            "message": "test",
            "llm_model": "nonexistent-model-id",
        },
        headers={"X-Run-ID": "test-run"},
    )
    
    assert response.status_code == 400
    assert "not found" in response.json()["detail"]


def test_chat_accepts_valid_provider_model():
    """POST /chat with valid provider+model passes validation."""
    from api.main import app
    from unittest.mock import patch, MagicMock
    
    client = TestClient(app)
    
    # Mock the A2A client to avoid actually invoking the supervisor
    with patch("api.chat.A2ACrewClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.send_task.return_value = '{"shortlist": [], "journey_steps": []}'
        mock_client_class.return_value = mock_client
        
        response = client.post(
            "/chat",
            json={
                "session_id": "test-session",
                "message": "test",
                "llm_provider": "eng_ai",
                "llm_model": "claude-sonnet-5",
            },
            headers={"X-Run-ID": "test-run"},
        )
        
        # Should not be a 400 validation error
        # (May be 500 or other if mocking is incomplete, but not 400)
        assert response.status_code != 400


def test_chat_accepts_none_provider_model():
    """POST /chat with no provider/model uses defaults."""
    from api.main import app
    from unittest.mock import patch, MagicMock
    
    client = TestClient(app)
    
    with patch("api.chat.A2ACrewClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.send_task.return_value = '{"shortlist": [], "journey_steps": []}'
        mock_client_class.return_value = mock_client
        
        response = client.post(
            "/chat",
            json={
                "session_id": "test-session",
                "message": "test",
            },
            headers={"X-Run-ID": "test-run"},
        )
        
        # Should not be a 400 validation error
        assert response.status_code != 400


def test_chat_forwards_provider_model_to_supervisor():
    """POST /chat includes llm_provider and llm_model in A2A context."""
    from api.main import app
    from unittest.mock import patch, MagicMock
    
    client = TestClient(app)
    
    with patch("api.chat.A2ACrewClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.send_task.return_value = '{"shortlist": [], "journey_steps": []}'
        mock_client_class.return_value = mock_client
        
        client.post(
            "/chat",
            json={
                "session_id": "test-session",
                "message": "test",
                "llm_provider": "eng_ai",
                "llm_model": "claude-sonnet-5",
            },
            headers={"X-Run-ID": "test-run"},
        )
        
        # Verify send_task was called with provider/model in context
        call_kwargs = mock_client.send_task.call_args[1]
        context = call_kwargs["context"]
        assert context["llm_provider"] == "eng_ai"
        assert context["llm_model"] == "claude-sonnet-5"
