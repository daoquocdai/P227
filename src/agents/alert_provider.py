from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

from google import genai
from google.genai import types

from src.agents.alert_schemas import AgentDecision, AgentExecutionResult, AgentJob
from src.agents.alert_tools import AlertAgentTools
from src.agents.gemini_tools import gemini_tool_from_definitions

SYSTEM_INSTRUCTIONS = """You are GuardianCam Alert Triage Agent.
Review only the current persisted GuardianCam Incident. First call get_incident_context.
Use get_event_context only when trigger evidence is useful. Never fabricate identifiers,
timestamps, scores, identities, recipients, or evidence. You do not replace Vision and cannot
delete or suppress the baseline alert. Finish by calling enrich_incident_alert exactly once with a verdict
of CONFIRMED_ALERT, UNCERTAIN, or DUPLICATE, an allowed severity, and a concise audit-safe
reason_summary. Do not provide chain-of-thought and do not request images.
Write reason_summary in concise, natural Vietnamese for a household user. Say "Hệ thống đã
ghi nhận X lần" using the authoritative occurrence count. Avoid implementation terms such as
algorithm, track, cosine similarity, model names, source epoch, or VisionProductPolicy. Do not
claim danger, crime, unconsciousness, or immobility without deterministic evidence."""


class AlertAgentProviderError(RuntimeError):
    pass


class AlertAgentModelProvider(ABC):
    @abstractmethod
    async def run(self, job: AgentJob, tools: AlertAgentTools) -> AgentExecutionResult:
        raise NotImplementedError


class GeminiAlertAgentProvider(AlertAgentModelProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_tool_steps: int,
        client: Any | None = None,
    ) -> None:
        self._client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )
        self._model = model
        self._max_tool_steps = max_tool_steps

    async def run(self, job: AgentJob, tools: AlertAgentTools) -> AgentExecutionResult:
        contents: list[types.Content] = [
            types.UserContent(
                parts=[
                    types.Part.from_text(
                        text=f"Review the persisted {job.event_type} incident assigned to this execution."
                    )
                ]
            )
        ]
        tool = gemini_tool_from_definitions(tools.definitions())
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTIONS,
            tools=[tool],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        calls = 0
        for _ in range(self._max_tool_steps):
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
            function_calls = response.function_calls or []
            if not function_calls:
                raise AlertAgentProviderError("model_finished_without_enrichment")
            model_content = response.candidates[0].content
            if model_content is None:
                raise AlertAgentProviderError("malformed_response")
            contents.append(model_content)
            response_parts = []
            for call in function_calls:
                calls += 1
                if calls > self._max_tool_steps:
                    raise AlertAgentProviderError("tool_step_limit")
                name = call.name or ""
                arguments = dict(call.args or {})
                try:
                    raw_arguments = json.dumps(arguments, ensure_ascii=False)
                except (TypeError, ValueError) as exc:
                    raise AlertAgentProviderError("invalid_function_arguments") from exc
                result = await asyncio.to_thread(tools.execute, name, raw_arguments)
                if name == "enrich_incident_alert":
                    decision = AgentDecision.model_validate(result)
                    return AgentExecutionResult(
                        decision=decision,
                        tool_calls=calls,
                        applied=bool(result.get("applied")),
                        no_op_reason=result.get("no_op_reason"),
                    )
                response_parts.append(
                    types.Part.from_function_response(name=name, response={"result": result})
                )
            contents.append(types.Content(role="tool", parts=response_parts))
        raise AlertAgentProviderError("tool_step_limit")


class DeterministicAlertAgentProvider(AlertAgentModelProvider):
    """Local-first fallback triage agent running without external API key."""

    async def run(self, job: AgentJob, tools: AlertAgentTools) -> AgentExecutionResult:
        inc = await asyncio.to_thread(tools.execute, "get_incident_context", "{}")
        evt = {}
        try:
            evt = await asyncio.to_thread(tools.execute, "get_event_context", "{}")
        except Exception:
            pass

        from src.agents.nodes.reasoning import evaluate_triage_severity

        confidence = float(evt.get("confidence") or inc.get("latest_event", {}).get("confidence") or 0.0)
        triage = evaluate_triage_severity(
            incident_type=inc.get("incident_type", job.event_type),
            ai_confidence=confidence,
            occurrence_count=int(inc.get("occurrence_count", 1)),
            location=inc.get("camera", {}).get("location", "chưa xác định"),
        )

        enrich_args = json.dumps({
            "verdict": triage["verdict"],
            "severity": triage["severity"],
            "reason_summary": triage["reasoning"],
        })
        res = await asyncio.to_thread(tools.execute, "enrich_incident_alert", enrich_args)
        decision = AgentDecision.model_validate(res)
        return AgentExecutionResult(
            decision=decision,
            tool_calls=2,
            applied=bool(res.get("applied")),
            no_op_reason=res.get("no_op_reason"),
        )

