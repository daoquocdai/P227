from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape
from typing import Protocol

import requests

from src.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CallResult:
    succeeded: bool
    provider_reference: str | None = None
    error_code: str | None = None
    retryable: bool = False


class EmergencyCallProvider(Protocol):
    def call(self, *, phone_number: str, incident_id: str, message: str) -> CallResult: ...


class TwilioEmergencyCallProvider:
    """Small Twilio REST adapter using inline TwiML; credentials stay in env settings."""

    def __init__(self, settings: Settings, *, timeout_seconds: float = 10.0) -> None:
        self._account_sid = settings.twilio_account_sid.strip()
        self._auth_token = settings.twilio_auth_token.strip()
        self._from_phone = settings.twilio_from_phone_number.strip()
        self._timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return bool(self._account_sid and self._auth_token and self._from_phone)

    def call(self, *, phone_number: str, incident_id: str, message: str) -> CallResult:
        if not self.available:
            return CallResult(False, error_code="TWILIO_UNAVAILABLE", retryable=False)
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Calls.json"
        twiml = f'<Response><Say language="vi-VN">{escape(message)}</Say></Response>'
        try:
            response = requests.post(
                url,
                auth=(self._account_sid, self._auth_token),
                data={"To": phone_number, "From": self._from_phone, "Twiml": twiml},
                timeout=self._timeout_seconds,
            )
        except requests.Timeout:
            return CallResult(False, error_code="TWILIO_TIMEOUT", retryable=True)
        except requests.RequestException:
            return CallResult(False, error_code="TWILIO_NETWORK_ERROR", retryable=True)
        if 200 <= response.status_code < 300:
            try:
                reference = response.json().get("sid")
            except ValueError:
                reference = None
            return CallResult(True, provider_reference=reference)
        retryable = response.status_code == 429 or response.status_code >= 500
        return CallResult(False, error_code=f"TWILIO_HTTP_{response.status_code}", retryable=retryable)


class LoggingEmergencyCallProvider:
    """No-cost development observer. It deliberately never reports a real call as successful."""

    def call(self, *, phone_number: str, incident_id: str, message: str) -> CallResult:
        logger.error(
            "Emergency call not placed: logging provider selected incident=%s destination_suffix=%s",
            incident_id,
            phone_number[-4:],
        )
        return CallResult(False, error_code="DEV_LOG_ONLY", retryable=False)


def build_emergency_call_provider(settings: Settings) -> EmergencyCallProvider:
    if settings.emergency_call_provider == "logging":
        return LoggingEmergencyCallProvider()
    return TwilioEmergencyCallProvider(settings)
