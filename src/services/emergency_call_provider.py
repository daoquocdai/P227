from __future__ import annotations

import logging
from dataclasses import dataclass
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
    """Twilio REST adapter.

    Uses the Trial-account-compatible payload:
        To  – destination number
        Url – Twilio hosted TTS template

    ``From`` and ``Twiml`` are intentionally omitted; Trial accounts reject them.
    Credentials (Account SID / Auth Token) are passed via HTTP Basic Auth.
    """

    # Twilio hosted TTS endpoint – no custom TwiML required for Trial.
    _TTS_URL = "https://webhooks.twilio.com/v1/Voice/Template/voice_text_to_speech"

    def __init__(self, settings: Settings, *, timeout_seconds: float = 10.0) -> None:
        self._account_sid = settings.twilio_account_sid.strip()
        self._auth_token = settings.twilio_auth_token.strip()
        # _from_phone is kept in the provider so callers can inspect it,
        # but it is NOT sent in the Trial payload (avoids "limited parameter
        # access" 400 from Twilio).
        self._from_phone = settings.twilio_from_phone_number.strip()
        self._timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        """True when the minimum credentials for a Trial call are present."""
        return bool(self._account_sid and self._auth_token)

    def call(self, *, phone_number: str, incident_id: str, message: str) -> CallResult:
        if not self.available:
            return CallResult(False, error_code="TWILIO_UNAVAILABLE", retryable=False)

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Calls.json"
        # Trial-compatible payload – only To + Url.
        data = {
            "To": phone_number,
            "Url": self._TTS_URL,
        }

        try:
            response = requests.post(
                url,
                auth=(self._account_sid, self._auth_token),
                data=data,
                timeout=self._timeout_seconds,
            )
        except requests.Timeout:
            logger.warning(
                "Twilio call timed out incident=%s destination_suffix=%s",
                incident_id,
                phone_number[-4:],
            )
            return CallResult(False, error_code="TWILIO_TIMEOUT", retryable=True)
        except requests.RequestException as exc:
            logger.warning(
                "Twilio network error incident=%s destination_suffix=%s error=%s",
                incident_id,
                phone_number[-4:],
                type(exc).__name__,
            )
            return CallResult(False, error_code="TWILIO_NETWORK_ERROR", retryable=True)

        if 200 <= response.status_code < 300:
            try:
                reference = response.json().get("sid")
            except ValueError:
                reference = None
            return CallResult(True, provider_reference=reference)

        # --- Error path: parse Twilio JSON for a richer error_code ---
        twilio_code: int | None = None
        twilio_message: str | None = None
        try:
            body = response.json()
            twilio_code = body.get("code")
            twilio_message = body.get("message")
        except ValueError:
            pass

        if twilio_code is not None:
            error_code = f"TWILIO_{twilio_code}"
        else:
            error_code = f"TWILIO_HTTP_{response.status_code}"

        retryable = response.status_code == 429 or response.status_code >= 500

        logger.error(
            "Twilio call failed incident=%s destination_suffix=%s http_status=%s twilio_code=%s message=%s",
            incident_id,
            phone_number[-4:],
            response.status_code,
            twilio_code,
            twilio_message,
        )
        return CallResult(False, error_code=error_code, retryable=retryable)


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
