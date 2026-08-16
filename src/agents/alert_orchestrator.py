from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress

from src.agents.alert_provider import (
    AlertAgentModelProvider,
    AlertAgentProviderError,
    OpenAIAlertAgentProvider,
)
from src.agents.alert_schemas import AgentJob
from src.agents.alert_tools import AlertAgentToolError, AlertAgentTools
from src.config import Settings, get_settings
from src.services.agent_trace_service import AgentTraceService
from src.services.alert_broadcaster import alert_broadcaster
from src.services.sqlite_event_repository import stable_uuid

logger = logging.getLogger(__name__)


class AlertAgentOrchestrator:
    """Bounded, single-consumer Agent execution isolated from Vision workers."""

    def __init__(
        self,
        settings: Settings | None = None,
        provider: AlertAgentModelProvider | None = None,
        trace: AgentTraceService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.trace = trace or AgentTraceService()
        self.provider = provider
        self._queue: asyncio.Queue[str] | None = None
        self._jobs_by_incident: dict[str, AgentJob] = {}
        self._consumer: asyncio.Task | None = None
        self._accepting = False

    @property
    def enabled(self) -> bool:
        return self.settings.alert_agent_enabled and bool(self.settings.openai_api_key)

    @property
    def queue_capacity(self) -> int:
        return self.settings.alert_agent_queue_capacity

    def start(self) -> None:
        self._queue = asyncio.Queue(maxsize=self.queue_capacity)
        self._accepting = True
        if not self.enabled:
            logger.warning("Alert Agent disabled or OPENAI_API_KEY unavailable; baseline alerts remain active")
            return
        if self.provider is None:
            self.provider = OpenAIAlertAgentProvider(
                api_key=self.settings.openai_api_key,
                model=self.settings.alert_agent_model,
                timeout_seconds=self.settings.alert_agent_timeout_seconds,
                max_tool_steps=self.settings.alert_agent_max_tool_steps,
            )
        self._consumer = asyncio.create_task(self._consume(), name="alert-agent-consumer")

    def enqueue(
        self, incident_id: str, external_event_id: str, alert_id: str, event_type: str, incident_version: int
    ) -> bool:
        if not self.enabled or not self._accepting or self._queue is None:
            return False
        job = AgentJob.create(
            incident_id, stable_uuid(external_event_id, "event"), alert_id, event_type, incident_version
        )
        if incident_id in self._jobs_by_incident:
            if incident_version > self._jobs_by_incident[incident_id].incident_version:
                self._jobs_by_incident[incident_id] = job
            return True
        self._jobs_by_incident[incident_id] = job
        try:
            self._queue.put_nowait(incident_id)
            return True
        except asyncio.QueueFull:
            self._jobs_by_incident.pop(incident_id, None)
            logger.error("Alert Agent queue saturated; baseline alert preserved event=%s", job.event_id)
            return False

    async def _consume(self) -> None:
        assert self._queue is not None
        while True:
            incident_id = await self._queue.get()
            job = self._jobs_by_incident[incident_id]
            try:
                await self._execute(job)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - worker must isolate individual failures
                logger.exception("Unexpected Alert Agent worker failure event=%s", job.event_id)
            finally:
                latest = self._jobs_by_incident.get(incident_id)
                if latest is not None and latest.incident_version > job.incident_version:
                    try:
                        self._queue.put_nowait(incident_id)
                    except asyncio.QueueFull:
                        logger.error(
                            "Alert Agent coalesced follow-up could not be queued incident=%s",
                            incident_id,
                        )
                        self._jobs_by_incident.pop(incident_id, None)
                else:
                    self._jobs_by_incident.pop(incident_id, None)
                self._queue.task_done()

    async def _execute(self, job: AgentJob) -> None:
        assert self.provider is not None
        started = time.perf_counter()
        run = await asyncio.to_thread(
            self.trace.create_or_get_run,
            job.incident_id,
            job.event_id,
            job.alert_id,
            self.settings.alert_agent_model,
            job.incident_version,
            job.attempt,
        )
        if run["status"] == "completed":
            return
        run_id = run["id"]
        await asyncio.to_thread(self.trace.mark_running, run_id)
        tools = AlertAgentTools(job.incident_id, job.event_id, job.alert_id, job.incident_version, run_id, self.trace)
        error_code = "provider_error"
        for attempt in range(1, self.settings.alert_agent_max_attempts + 1):
            try:
                result = await asyncio.wait_for(
                    self.provider.run(job, tools), timeout=self.settings.alert_agent_timeout_seconds
                )
                latency = (time.perf_counter() - started) * 1000
                if not result.applied:
                    await asyncio.to_thread(self.trace.skip, run_id, result.no_op_reason or "stale", latency)
                    return
                await asyncio.to_thread(
                    self.trace.complete,
                    run_id,
                    result.decision.verdict,
                    result.decision.severity,
                    result.decision.reason_summary,
                    latency,
                )
                await alert_broadcaster.publish(
                    {"type": "alert_agent_reviewed", "alert_id": job.alert_id, "run_id": run_id}
                )
                return
            except TimeoutError:
                error_code = "timeout"
            except (AlertAgentToolError, AlertAgentProviderError) as exc:
                error_code = type(exc).__name__[:100]
                break
            except Exception as exc:  # noqa: BLE001 - provider errors are sanitized below
                error_code = type(exc).__name__[:100]
            if attempt < self.settings.alert_agent_max_attempts:
                await asyncio.sleep(min(2 ** (attempt - 1), 4))
        latency = (time.perf_counter() - started) * 1000
        await asyncio.to_thread(self.trace.fail, run_id, error_code, latency)
        await alert_broadcaster.publish({"type": "alert_agent_failed", "alert_id": job.alert_id, "run_id": run_id})

    async def stop(self) -> None:
        self._accepting = False
        if self._consumer is None:
            self._queue = None
            return
        assert self._queue is not None
        try:
            await asyncio.wait_for(self._queue.join(), self.settings.alert_agent_shutdown_timeout_seconds)
        except TimeoutError:
            logger.warning("Alert Agent shutdown timed out with %s pending jobs", self._queue.qsize())
        self._consumer.cancel()
        with suppress(asyncio.CancelledError):
            await self._consumer
        self._consumer = None
        self._queue = None


alert_agent_orchestrator = AlertAgentOrchestrator()
