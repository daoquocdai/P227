from types import SimpleNamespace

import pytest
from google.genai import types

from src.agents.alert_orchestrator import AlertAgentOrchestrator
from src.agents.alert_provider import (
    AlertAgentProviderError,
    DeterministicAlertAgentProvider,
    GeminiAlertAgentProvider,
)
from src.agents.alert_schemas import AgentJob
from src.agents.qa_agent import SecurityQAAgent
from src.api.agent import ChatQueryRequest, agent_chat
from src.config import Settings


def response(*, text=None, calls=None):
    calls = calls or []
    parts = [types.Part.from_function_call(name=call.name, args=call.args) for call in calls]
    if text is not None:
        parts.append(types.Part.from_text(text=text))
    content = types.ModelContent(parts=parts)
    return SimpleNamespace(
        text=text,
        function_calls=calls,
        candidates=[SimpleNamespace(content=content)],
    )


class FakeModels:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def generate_content(self, **kwargs):
        self.requests.append(kwargs)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def fake_client(*responses):
    models = FakeModels(responses)
    return SimpleNamespace(aio=SimpleNamespace(models=models)), models


class FakeAlertTools:
    def __init__(self):
        self.executed = []

    @staticmethod
    def definitions():
        return [
            {
                "type": "function",
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {}},
            }
            for name in ("get_incident_context", "enrich_incident_alert")
        ]

    def execute(self, name, raw_arguments):
        self.executed.append((name, raw_arguments))
        if name == "get_incident_context":
            return {"occurrence_count": 1}
        if name == "enrich_incident_alert":
            return {
                "verdict": "CONFIRMED_ALERT",
                "severity": "high",
                "reason_summary": "Hệ thống đã ghi nhận 1 lần.",
                "applied": True,
            }
        raise ValueError("unknown tool")


def job():
    return AgentJob.create("incident", "event", "alert", "fall", 1)


@pytest.mark.asyncio
async def test_orchestrator_selects_deterministic_provider_without_key():
    orchestrator = AlertAgentOrchestrator(
        settings=Settings(_env_file=None, alert_agent_enabled=True, gemini_api_key="")
    )
    orchestrator.start()
    assert isinstance(orchestrator.provider, DeterministicAlertAgentProvider)
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_orchestrator_selects_gemini_provider_with_key():
    orchestrator = AlertAgentOrchestrator(
        settings=Settings(_env_file=None, alert_agent_enabled=True, gemini_api_key="test-only")
    )
    orchestrator.start()
    assert isinstance(orchestrator.provider, GeminiAlertAgentProvider)
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_qa_gemini_normal_text_preserves_contract():
    client, _ = fake_client(response(text="Camera đang hoạt động."))
    result = await SecurityQAAgent(api_key="test", client=client).answer("Trạng thái camera thế nào?")
    assert result == {"answer": "Camera đang hoạt động.", "data": {}}


@pytest.mark.asyncio
async def test_qa_gemini_function_call_executes_and_parses_args(monkeypatch):
    call = types.FunctionCall(name="query_recent_incidents", args={"limit": 3})
    client, models = fake_client(response(calls=[call]), response(text="Có dữ liệu."))
    monkeypatch.setattr(
        SecurityQAAgent,
        "_execute_tool",
        staticmethod(lambda name, args: {"name": name, "limit": args["limit"]}),
    )
    result = await SecurityQAAgent(api_key="test", client=client).answer("Tóm tắt sự cố camera")
    assert result["data"]["query_recent_incidents"]["limit"] == 3
    assert len(models.requests) == 2


@pytest.mark.asyncio
async def test_alert_gemini_tool_loop_returns_validated_decision():
    client, models = fake_client(
        response(calls=[types.FunctionCall(name="get_incident_context", args={})]),
        response(
            calls=[
                types.FunctionCall(
                    name="enrich_incident_alert",
                    args={
                        "verdict": "CONFIRMED_ALERT",
                        "severity": "high",
                        "reason_summary": "Hệ thống đã ghi nhận 1 lần.",
                    },
                )
            ]
        ),
    )
    tools = FakeAlertTools()
    provider = GeminiAlertAgentProvider(
        api_key="test", model="gemini-3.5-flash-lite", timeout_seconds=1, max_tool_steps=4, client=client
    )
    result = await provider.run(job(), tools)
    assert result.decision.verdict == "CONFIRMED_ALERT"
    assert result.tool_calls == 2
    assert '"severity": "high"' in tools.executed[1][1]
    assert len(models.requests) == 2


@pytest.mark.asyncio
async def test_alert_gemini_tool_step_limit():
    repeated = response(calls=[types.FunctionCall(name="get_incident_context", args={})])
    client, _ = fake_client(repeated, repeated)
    provider = GeminiAlertAgentProvider(
        api_key="test", model="gemini-3.5-flash-lite", timeout_seconds=1, max_tool_steps=2, client=client
    )
    with pytest.raises(AlertAgentProviderError, match="tool_step_limit"):
        await provider.run(job(), FakeAlertTools())


@pytest.mark.asyncio
async def test_qa_gemini_error_uses_deterministic_fallback():
    client, _ = fake_client(RuntimeError("quota exceeded"))
    result = await SecurityQAAgent(api_key="test", client=client).answer("Trạng thái camera thế nào?")
    assert "cameras" in result["data"]


@pytest.mark.asyncio
async def test_agent_chat_endpoint_contract_is_unchanged():
    qa_agent = SimpleNamespace(
        answer=lambda _query: _async_result({"answer": "An toàn.", "data": {"camera": "online"}})
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(qa_agent=qa_agent)))
    result = await agent_chat(ChatQueryRequest(query="Trạng thái camera?"), request)
    assert result.model_dump() == {"answer": "An toàn.", "data": {"camera": "online"}}


async def _async_result(value):
    return value
