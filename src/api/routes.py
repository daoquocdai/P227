from fastapi import APIRouter, HTTPException
from src.agents.graph import agent
from src.models.schemas import EventRequest, AgentDecisionResponse

router = APIRouter()

@router.post("/evaluate-event", response_model=AgentDecisionResponse)
async def evaluate_security_event(request: EventRequest):
    """Giao việc cho AI Agent phân tích ngữ cảnh sự kiện ngã/người lạ."""
    try:
        # Truyền thông tin sự kiện vào cho LangGraph Agent lập luận
        result = await agent.ainvoke({
            "event": request.event_type,
            "location": request.camera_location,
            "time": request.timestamp
        })
        
        return AgentDecisionResponse(
            threat_level=result.get("threat_level", "Unknown"),
            action_taken=result.get("action", "Wait"),
            reasoning=result.get("reasoning", "Không có dữ liệu phân tích")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
async def agent_status():
    """Kiểm tra trạng thái Agent."""
    return {"status": "ready", "agent": "Security Orchestrator Agent v1.0"}