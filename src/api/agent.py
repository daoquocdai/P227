from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.agents.qa_agent import SecurityQAAgent
from src.agents.summary_agent import IncidentSummaryAgent

router = APIRouter(prefix="/agent", tags=["agent"])


class ChatQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Câu hỏi ngôn ngữ tự nhiên từ người dùng")


class ChatQueryResponse(BaseModel):
    answer: str
    data: dict[str, Any] = {}


@router.post("/chat", response_model=ChatQueryResponse)
async def agent_chat(request_body: ChatQueryRequest, request: Request) -> ChatQueryResponse:
    """Trợ lý Hỏi-Đáp Nhật ký An ninh (Security Q&A Assistant)."""
    qa_agent: SecurityQAAgent = getattr(request.app.state, "qa_agent", SecurityQAAgent())
    result = await qa_agent.answer(request_body.query)
    return ChatQueryResponse(answer=result["answer"], data=result.get("data", {}))


@router.post("/summary/{incident_id}")
@router.get("/summary/{incident_id}")
async def generate_incident_summary(incident_id: str, request: Request) -> dict[str, Any]:
    """Tạo timeline và tóm tắt sự cố (Incident Summary & Timeline Agent)."""
    summary_agent: IncidentSummaryAgent = getattr(request.app.state, "summary_agent", IncidentSummaryAgent())
    result = await summary_agent.generate_summary(incident_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail="Incident not found or summary generation failed")
    return result
