"""Tests for TwilioEmergencyCallProvider – G through K.

All tests use mocked ``requests.post``; no real Twilio call is made.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests as requests_lib

from src.config import get_settings
from src.services.emergency_call_provider import TwilioEmergencyCallProvider


def _make_settings(**kwargs):
    return get_settings().model_copy(
        update={
            "twilio_account_sid": "ACtest123",
            "twilio_auth_token": "authtoken456",
            "twilio_from_phone_number": "+15005550006",  # present but must NOT be sent
            **kwargs,
        }
    )


def _provider(**kwargs) -> TwilioEmergencyCallProvider:
    return TwilioEmergencyCallProvider(_make_settings(**kwargs))


def _fake_response(status_code: int, body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


def _call(provider: TwilioEmergencyCallProvider, phone: str = "+84901234567"):
    return provider.call(phone_number=phone, incident_id="incident-test", message="Test message")


# ---------------------------------------------------------------------------
# G: Twilio request payload – exactly To + Url, no From, no Twiml
# ---------------------------------------------------------------------------

def test_G_twilio_payload_contains_only_to_and_url():
    """G: POST payload must contain To and Url, must NOT contain From or Twiml."""
    provider = _provider()
    with patch("requests.post") as mock_post:
        mock_post.return_value = _fake_response(201, {"sid": "CA123", "status": "queued"})
        _call(provider)

    assert mock_post.called
    _, kwargs = mock_post.call_args
    data = kwargs.get("data", {})

    assert "To" in data, "Payload must contain 'To'"
    assert "Url" in data, "Payload must contain 'Url'"
    assert "From" not in data, "Payload must NOT contain 'From' (Trial account restriction)"
    assert "Twiml" not in data, "Payload must NOT contain 'Twiml' (Trial account restriction)"


# ---------------------------------------------------------------------------
# H: HTTP 201 → succeeded True, provider_reference == "CA123"
# ---------------------------------------------------------------------------

def test_H_http_201_succeeded_true_and_call_sid_returned():
    """H: Twilio returns 201 {sid, status:queued} → succeeded=True, provider_reference=CA123."""
    provider = _provider()
    with patch("requests.post") as mock_post:
        mock_post.return_value = _fake_response(201, {"sid": "CA123", "status": "queued"})
        result = _call(provider)

    assert result.succeeded is True
    assert result.provider_reference == "CA123"
    assert result.error_code is None


def test_H_http_200_also_succeeds():
    """HTTP 200 is also a 2xx success."""
    provider = _provider()
    with patch("requests.post") as mock_post:
        mock_post.return_value = _fake_response(200, {"sid": "CA200"})
        result = _call(provider)

    assert result.succeeded is True
    assert result.provider_reference == "CA200"


# ---------------------------------------------------------------------------
# I: Twilio JSON 400 with code field → error_code = TWILIO_{code}, retryable False
# ---------------------------------------------------------------------------

def test_I_twilio_json_400_with_code_produces_richer_error_code():
    """I: 400 + JSON {code:21219} → error_code=TWILIO_21219, succeeded=False, retryable=False."""
    provider = _provider()
    with patch("requests.post") as mock_post:
        mock_post.return_value = _fake_response(
            400,
            {"code": 21219, "message": "Unverified number", "status": 400},
        )
        result = _call(provider)

    assert result.succeeded is False
    assert result.error_code == "TWILIO_21219"
    assert result.retryable is False


def test_I_twilio_json_400_without_code_falls_back_to_http_error_code():
    """I-fallback: 400 without JSON code field → error_code=TWILIO_HTTP_400."""
    provider = _provider()
    with patch("requests.post") as mock_post:
        resp = MagicMock()
        resp.status_code = 400
        resp.json.side_effect = ValueError("not json")
        mock_post.return_value = resp
        result = _call(provider)

    assert result.succeeded is False
    assert result.error_code == "TWILIO_HTTP_400"
    assert result.retryable is False


def test_I_twilio_json_400_empty_body_falls_back_to_http_error_code():
    """I-fallback: 400 with JSON body but no 'code' key → error_code=TWILIO_HTTP_400."""
    provider = _provider()
    with patch("requests.post") as mock_post:
        mock_post.return_value = _fake_response(400, {"message": "bad request"})
        result = _call(provider)

    assert result.succeeded is False
    assert result.error_code == "TWILIO_HTTP_400"
    assert result.retryable is False


# ---------------------------------------------------------------------------
# J: HTTP 429 / 500 → retryable True
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_J_rate_limit_and_server_errors_are_retryable(status_code: int):
    """J: 429 / 5xx → retryable=True."""
    provider = _provider()
    with patch("requests.post") as mock_post:
        mock_post.return_value = _fake_response(status_code, {"code": 99999})
        result = _call(provider)

    assert result.succeeded is False
    assert result.retryable is True


# ---------------------------------------------------------------------------
# K: requests.Timeout / network exception → retryable True
# ---------------------------------------------------------------------------

def test_K_requests_timeout_returns_retryable():
    """K: requests.Timeout → CallResult(succeeded=False, retryable=True)."""
    provider = _provider()
    with patch("requests.post", side_effect=requests_lib.Timeout("timed out")):
        result = _call(provider)

    assert result.succeeded is False
    assert result.error_code == "TWILIO_TIMEOUT"
    assert result.retryable is True


def test_K_requests_network_error_returns_retryable():
    """K: requests.ConnectionError → CallResult(succeeded=False, retryable=True)."""
    provider = _provider()
    with patch("requests.post", side_effect=requests_lib.ConnectionError("network down")):
        result = _call(provider)

    assert result.succeeded is False
    assert result.error_code == "TWILIO_NETWORK_ERROR"
    assert result.retryable is True


# ---------------------------------------------------------------------------
# Availability check – only SID + token required (Trial doesn't need From)
# ---------------------------------------------------------------------------

def test_available_true_without_from_phone():
    """Trial account: available=True even when twilio_from_phone_number is empty."""
    provider = TwilioEmergencyCallProvider(
        _make_settings(twilio_from_phone_number="")
    )
    assert provider.available is True


def test_available_false_when_sid_missing():
    provider = TwilioEmergencyCallProvider(
        _make_settings(twilio_account_sid="")
    )
    assert provider.available is False


def test_available_false_when_token_missing():
    provider = TwilioEmergencyCallProvider(
        _make_settings(twilio_auth_token="")
    )
    assert provider.available is False


def test_unavailable_provider_returns_twilio_unavailable_without_network_call():
    """TWILIO_UNAVAILABLE is returned without any HTTP request being made."""
    provider = TwilioEmergencyCallProvider(
        _make_settings(twilio_account_sid="", twilio_auth_token="")
    )
    with patch("requests.post") as mock_post:
        result = _call(provider)

    mock_post.assert_not_called()
    assert result.error_code == "TWILIO_UNAVAILABLE"
    assert result.succeeded is False
    assert result.retryable is False
