from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from src.config import get_settings
from src.services.emergency_call_provider import TwilioEmergencyCallProvider

TTS_URL = "https://webhooks.twilio.com/v1/Voice/Template/voice_text_to_speech"


def settings(**updates):
    return get_settings().model_copy(
        update={
            "twilio_account_sid": "AC123",
            "twilio_auth_token": "secret",
            "twilio_from_phone_number": "",
            **updates,
        }
    )


def response(status_code: int, body=...):
    mocked = Mock(status_code=status_code)
    if body is ...:
        mocked.json.side_effect = ValueError("not JSON")
    else:
        mocked.json.return_value = body
    return mocked


def call(provider: TwilioEmergencyCallProvider):
    return provider.call(phone_number="+84829880105", incident_id="incident-1", message="Help")


def test_availability_requires_only_account_sid_and_auth_token():
    assert TwilioEmergencyCallProvider(settings(twilio_from_phone_number="")).available is True
    assert TwilioEmergencyCallProvider(settings(twilio_account_sid="")).available is False
    assert TwilioEmergencyCallProvider(settings(twilio_auth_token="")).available is False


def test_call_posts_exact_trial_payload(monkeypatch):
    post = Mock(return_value=response(201, {"sid": "CA123", "status": "queued"}))
    monkeypatch.setattr(requests, "post", post)
    provider = TwilioEmergencyCallProvider(settings(twilio_from_phone_number="+15005550006"))

    result = call(provider)

    assert result.succeeded is True
    assert result.provider_reference == "CA123"
    post.assert_called_once_with(
        "https://api.twilio.com/2010-04-01/Accounts/AC123/Calls.json",
        auth=("AC123", "secret"),
        data={"To": "+84829880105", "Url": TTS_URL},
        timeout=10.0,
    )
    data = post.call_args.kwargs["data"]
    assert "From" not in data
    assert "Twiml" not in data


def test_http_400_uses_twilio_json_error_code(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        Mock(return_value=response(400, {"code": 21219, "message": "unverified", "status": 400})),
    )

    result = call(TwilioEmergencyCallProvider(settings()))

    assert result.succeeded is False
    assert result.error_code == "TWILIO_21219"
    assert result.retryable is False


def test_non_json_http_400_uses_http_error_code(monkeypatch):
    monkeypatch.setattr(requests, "post", Mock(return_value=response(400)))

    result = call(TwilioEmergencyCallProvider(settings()))

    assert result.succeeded is False
    assert result.error_code == "TWILIO_HTTP_400"
    assert result.retryable is False


@pytest.mark.parametrize("status_code", [429, 500])
def test_retryable_http_statuses(monkeypatch, status_code):
    monkeypatch.setattr(requests, "post", Mock(return_value=response(status_code, {})))

    result = call(TwilioEmergencyCallProvider(settings()))

    assert result.succeeded is False
    assert result.error_code == f"TWILIO_HTTP_{status_code}"
    assert result.retryable is True


def test_timeout_is_retryable(monkeypatch):
    monkeypatch.setattr(requests, "post", Mock(side_effect=requests.Timeout("slow")))

    result = call(TwilioEmergencyCallProvider(settings()))

    assert result.succeeded is False
    assert result.error_code == "TWILIO_TIMEOUT"
    assert result.retryable is True


@pytest.mark.parametrize("exception", [requests.ConnectionError("offline"), requests.RequestException("network")])
def test_network_request_errors_are_retryable(monkeypatch, exception):
    monkeypatch.setattr(requests, "post", Mock(side_effect=exception))

    result = call(TwilioEmergencyCallProvider(settings()))

    assert result.succeeded is False
    assert result.error_code == "TWILIO_NETWORK_ERROR"
    assert result.retryable is True
