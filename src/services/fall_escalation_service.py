from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.config import Settings, get_settings
from src.database import database_connection
from src.services.alert_broadcaster import alert_broadcaster
from src.services.emergency_call_provider import CallResult, EmergencyCallProvider, build_emergency_call_provider
from src.services.sqlite_event_repository import SQLiteEventRepository

logger = logging.getLogger(__name__)
STAGE = "fall_unconfirmed"
GLOBAL_PROVIDER_FAILURES = {"TWILIO_UNAVAILABLE", "DEV_LOG_ONLY"}


@dataclass(frozen=True, slots=True)
class ClaimedCall:
    attempt_id: str
    incident_id: str
    alert_id: str
    contact_id: str
    phone_number: str
    location: str


@dataclass(frozen=True, slots=True)
class PersistedStateChange:
    alert_id: str


class FallEscalationService:
    """Persisted, deterministic polling policy for unconfirmed fall incidents."""

    def __init__(
        self,
        settings: Settings | None = None,
        provider: EmergencyCallProvider | None = None,
        *,
        now=None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or build_emergency_call_provider(self.settings)
        self._now = now or (lambda: datetime.now(UTC))
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopping = False

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name="fall-escalation-worker")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        self._stopping = True
        self._wake.set()
        try:
            async with asyncio.timeout(12):
                await asyncio.shield(task)
        except TimeoutError:
            logger.error("Fall escalation worker did not stop within provider timeout")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def request_evaluation(self) -> None:
        self._wake.set()

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self.evaluate_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - worker failure must not affect event ingestion
                logger.exception("Fall escalation evaluation failed")
            if self._stopping:
                return
            try:
                async with asyncio.timeout(self.settings.fall_escalation_poll_seconds):
                    await self._wake.wait()
            except TimeoutError:
                pass
            self._wake.clear()

    async def evaluate_once(self) -> int:
        if not self.settings.fall_escalation_enabled:
            return 0
        calls = 0
        for incident_id in self._eligible_incident_ids():
            decision = self._claim_next_attempt(incident_id)
            if isinstance(decision, PersistedStateChange):
                await self._broadcast_alert(decision.alert_id)
                continue
            if decision is None:
                continue
            claim = decision
            await asyncio.sleep(0)
            if not self._revalidate_claim(claim):
                continue
            message = (
                f"An Tâm Home phát hiện một trường hợp có khả năng té ngã tại {claim.location}. "
                f"Sau {self.settings.fall_call_after_seconds} giây chưa nhận được xác nhận an toàn. "
                "Vui lòng kiểm tra ngay."
            )
            try:
                result = await asyncio.to_thread(
                    self.provider.call,
                    phone_number=claim.phone_number,
                    incident_id=claim.incident_id,
                    message=message,
                )
            except Exception:  # noqa: BLE001 - provider boundary is isolated and retryable
                logger.exception("Emergency call provider failed incident=%s", claim.incident_id)
                result = CallResult(False, error_code="PROVIDER_EXCEPTION", retryable=True)
            self._record_result(claim, result)
            await self._broadcast_alert(claim.alert_id)
            calls += int(result.succeeded)
        return calls

    def _eligible_incident_ids(self) -> list[str]:
        now = self._now()
        with database_connection(initialize=False) as connection:
            rows = connection.execute(
                """SELECT i.id, i.opened_at, i.help_requested_at FROM incidents i
                   WHERE incident_type='fall' AND status IN ('OPEN','ACKNOWLEDGED')
                     AND EXISTS (
                       SELECT 1 FROM incident_events ie JOIN events e ON e.id=ie.event_id
                       WHERE ie.incident_id=i.id
                         AND json_extract(e.metadata_json,'$.source_event_type')='FALL_CONFIRMED'
                     )
                   ORDER BY opened_at, id"""
            ).fetchall()
        return [
            row["id"]
            for row in rows
            if row["help_requested_at"] is not None
            or _parse_timestamp(row["opened_at"]) + timedelta(seconds=self.settings.fall_call_after_seconds) <= now
        ]

    def _claim_next_attempt(self, incident_id: str) -> ClaimedCall | PersistedStateChange | None:
        now = self._now()
        with database_connection(initialize=False) as connection:
            connection.execute("BEGIN IMMEDIATE")
            incident = connection.execute(
                """SELECT i.*, a.id AS alert_id, c.location_label,
                          EXISTS(
                            SELECT 1 FROM incident_events ie JOIN events e ON e.id=ie.event_id
                            WHERE ie.incident_id=i.id
                              AND json_extract(e.metadata_json,'$.source_event_type')='FALL_CONFIRMED'
                          ) AS fall_confirmed
                   FROM incidents i JOIN alerts a ON a.incident_id=i.id
                   JOIN cameras c ON c.id=i.camera_id WHERE i.id=?""",
                (incident_id,),
            ).fetchone()
            if (
                incident is None
                or incident["incident_type"] != "fall"
                or not incident["fall_confirmed"]
                or incident["status"] == "RESOLVED_SAFE"
            ):
                return None
            due = _parse_timestamp(incident["opened_at"]) + timedelta(seconds=self.settings.fall_call_after_seconds)
            if incident["help_requested_at"] is None and due > now:
                return None
            if connection.execute(
                "SELECT 1 FROM emergency_escalation_attempts WHERE incident_id=? AND stage=? AND status='succeeded'",
                (incident_id, STAGE),
            ).fetchone():
                return None
            if connection.execute(
                "SELECT 1 FROM emergency_escalation_attempts WHERE incident_id=? AND stage=? AND status='claimed'",
                (incident_id, STAGE),
            ).fetchone():
                return None
            # Determine the primary contact for this incident.
            # The primary contact is the first active contact in (priority, created_at, id) order.
            # Once established, ALL retry attempts go to the same primary contact;
            # there is NO fallback to a second contact on failure.
            contacts = connection.execute(
                "SELECT * FROM emergency_contacts WHERE is_active=1 ORDER BY priority, created_at, id"
            ).fetchall()
            if not contacts:
                inserted = connection.execute(
                    """INSERT OR IGNORE INTO emergency_escalation_attempts
                       (id,incident_id,contact_id,status,attempt_number,incident_version,idempotency_key,error_code)
                       VALUES (?,?,NULL,'failed',1,?,?,'NO_ACTIVE_CONTACT')""",
                    (str(uuid4()), incident_id, incident["version"], f"{incident_id}:{STAGE}:none:1"),
                )
                if inserted.rowcount:
                    logger.error("Fall escalation has no active emergency contact incident=%s", incident_id)
                    return PersistedStateChange(incident["alert_id"])
                return None
            for contact in contacts:
                attempts = connection.execute(
                    """SELECT * FROM emergency_escalation_attempts
                       WHERE incident_id=? AND stage=? AND contact_id=? ORDER BY attempt_number DESC LIMIT 1""",
                    (incident_id, STAGE, contact["id"]),
                ).fetchone()
                if attempts is None:
                    attempt_number = 1
                elif attempts["error_code"] in GLOBAL_PROVIDER_FAILURES:

            # Resolve primary contact: prefer the contact already used in the
            # attempt chain (preserves identity across contact-list changes),
            # otherwise use the current first active contact.
            prior_attempt = connection.execute(
                """SELECT contact_id FROM emergency_escalation_attempts
                   WHERE incident_id=? AND stage=? AND contact_id IS NOT NULL
                   ORDER BY attempt_number ASC LIMIT 1""",
                (incident_id, STAGE),
            ).fetchone()
            if prior_attempt is not None:
                # Stick to the contact already in use for this incident.
                primary_id = prior_attempt["contact_id"]
                contact = next((c for c in contacts if c["id"] == primary_id), None)
                if contact is None:
                    # Primary contact has since been deactivated; treat as no contact.
                    return None
                elif attempts["status"] == "failed" and attempts["retryable"]:
                    if attempts["attempt_number"] >= self.settings.fall_call_max_attempts:
                        continue
                    retry_at = _parse_timestamp(attempts["updated_at"]) + timedelta(
                        seconds=self.settings.fall_call_retry_seconds
                    )
                    if retry_at > now:
                        return None
                    attempt_number = attempts["attempt_number"] + 1
                elif attempts["status"] == "failed":
                    continue
                else:
            else:
                contact = contacts[0]

            attempts = connection.execute(
                """SELECT * FROM emergency_escalation_attempts
                   WHERE incident_id=? AND stage=? AND contact_id=? ORDER BY attempt_number DESC LIMIT 1""",
                (incident_id, STAGE, contact["id"]),
            ).fetchone()

            if attempts is None:
                attempt_number = 1
            elif attempts["error_code"] in GLOBAL_PROVIDER_FAILURES:
                # Global provider failure (e.g. TWILIO_UNAVAILABLE) – stop entirely.
                return None
            elif attempts["status"] == "failed" and attempts["retryable"]:
                if attempts["attempt_number"] >= self.settings.fall_call_max_attempts:
                    # Max retries exhausted for primary contact – stop without fallback.
                    return None
                attempt_id = str(uuid4())
                connection.execute(
                    """INSERT INTO emergency_escalation_attempts
                       (id,incident_id,contact_id,status,attempt_number,incident_version,idempotency_key)
                       VALUES (?,?,?,'claimed',?,?,?)""",
                    (
                        attempt_id,
                        incident_id,
                        contact["id"],
                        attempt_number,
                        incident["version"],
                        f"{incident_id}:{STAGE}:{contact['id']}:{attempt_number}",
                    ),
                retry_at = _parse_timestamp(attempts["updated_at"]) + timedelta(
                    seconds=self.settings.fall_call_retry_seconds
                )
                return ClaimedCall(
                if retry_at > now:
                    # Not yet time for the next retry.
                    return None
                attempt_number = attempts["attempt_number"] + 1
            elif attempts["status"] == "failed":
                # Non-retryable failure for primary contact – stop without fallback.
                return None
            else:
                # Already succeeded or in-flight.
                return None

            attempt_id = str(uuid4())
            connection.execute(
                """INSERT INTO emergency_escalation_attempts
                   (id,incident_id,contact_id,status,attempt_number,incident_version,idempotency_key)
                   VALUES (?,?,?,'claimed',?,?,?)""",
                (
                    attempt_id,
                    incident_id,
                    incident["alert_id"],
                    contact["id"],
                    contact["phone_e164"],
                    incident["location_label"],
                )
                    attempt_number,
                    incident["version"],
                    f"{incident_id}:{STAGE}:{contact['id']}:{attempt_number}",
                ),
            )
            return ClaimedCall(
                attempt_id,
                incident_id,
                incident["alert_id"],
                contact["id"],
                contact["phone_e164"],
                incident["location_label"],
            )
        return None

    @staticmethod
    def _revalidate_claim(claim: ClaimedCall) -> bool:
        with database_connection(initialize=False) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = connection.execute(
                """SELECT i.status AS incident_status, e.status AS attempt_status
                   FROM incidents i JOIN emergency_escalation_attempts e ON e.incident_id=i.id
                   WHERE i.id=? AND e.id=?""",
                (claim.incident_id, claim.attempt_id),
            ).fetchone()
            if state is None or state["attempt_status"] != "claimed":
                return False
            if state["incident_status"] == "RESOLVED_SAFE":
                connection.execute(
                    """UPDATE emergency_escalation_attempts SET status='cancelled',error_code='RESOLVED_SAFE',
                       updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND status='claimed'""",
                    (claim.attempt_id,),
                )
                return False
            return True

    @staticmethod
    def _record_result(claim: ClaimedCall, result: CallResult) -> None:
        with database_connection(initialize=False) as connection:
            connection.execute(
                """UPDATE emergency_escalation_attempts SET status=?,provider_reference=?,error_code=?,retryable=?,
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND status='claimed'""",
                (
                    "succeeded" if result.succeeded else "failed",
                    result.provider_reference,
                    result.error_code,
                    int(result.retryable),
                    claim.attempt_id,
                ),
            )
        if not result.succeeded:
            logger.error(
                "Emergency call failed incident=%s error_code=%s retryable=%s",
                claim.incident_id,
                result.error_code,
                result.retryable,
            )

    @staticmethod
    async def _broadcast_alert(alert_id: str) -> None:
        alert = SQLiteEventRepository().get_alert(alert_id)
        await alert_broadcaster.publish({"type": "alert_updated", "alert": alert})


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
