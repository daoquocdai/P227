from fastapi import APIRouter

from src.config import get_settings

router = APIRouter()


@router.get("/status")
async def system_status():
    """Baseline Local Hub status; Agent is intentionally outside the event flow."""
    return {
        "status": "ready",
        "service": "GuardianCam Local Hub",
        "vision_integration": "in_process_queue",
        "agent_enabled": get_settings().alert_agent_enabled,
    }
