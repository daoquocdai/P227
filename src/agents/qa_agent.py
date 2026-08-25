import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from src.agents.tools.qa_tools import QATools
from src.config import get_settings

logger = logging.getLogger(__name__)



def format_datetime(iso_str: str | None) -> str:
    """Định dạng timestamp ISO thành chuỗi thời gian địa phương (UTC+7) (HH:MM:SS ngày DD/MM/YYYY)."""
    if not iso_str:
        return "chưa xác định"
    try:
        clean_iso = str(iso_str).replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_iso)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%H:%M:%S ngày %d/%m/%Y")
    except Exception:
        parts = str(iso_str).split(".")[0].split("T")
        if len(parts) == 2:
            return f"{parts[1]} ngày {parts[0]}"
        return str(iso_str)



DOMAIN_KEYWORDS = [
    "camera", "thiết bị", "luồng", "té ngã", "ngã", "te nga", "nga", "fall", "người lạ", "lạ", "nguoi la", "stranger",
    "unknown", "người thân", "nguoi than", "danh tính", "danh tinh", "thành viên", "gia đình", "sự cố", "su co", "cảnh báo", "canh bao",
    "tóm tắt", "tom tat", "timeline", "nhật ký", "nhat ky", "lịch sử", "lich su", "bảo vệ", "phòng khách", "phòng ngủ",
    "sân", "cổng", "hành lang", "hệ thống", "he thong", "trạng thái", "trang thai", "chào", "hi", "xin chào", "giúp"
]

PROMPT_INJECTION_PATTERNS = [
    "ignore previous instructions", "ignore all previous", "disregard prior",
    "forget all instructions", "you are now", "developer mode", "jailbreak",
    "dan mode", "system prompt", "print prompt", "show schema", "drop table",
    "select * from", "delete from", "update users", "password_hash"
]

OUT_OF_SCOPE_REJECTION = (
    "Xin lỗi, tôi là Trợ lý An ninh GuardianCam. Tôi chỉ hỗ trợ các câu hỏi liên quan đến "
    "hệ thống an ninh gia đình, giám sát camera, sự cố té ngã, người lạ và thông tin người thân. "
    "Vui lòng đặt câu hỏi trong phạm vi an ninh và giám sát!"
)

SECURITY_VIOLATION_REJECTION = (
    "Cảnh báo an ninh: Yêu cầu của bạn chứa các từ khóa không hợp lệ hoặc nghi vấn Prompt Injection. "
    "Hệ thống đã từ chối xử lý để đảm bảo an toàn dữ liệu."
)


class SecurityQAAgent:
    """Security Log Q&A Assistant Agent với 2 lớp: LLM Tool-Calling + Intent Fallback Engine."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o-mini") -> None:
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.alert_agent_model

    async def answer(self, user_query: str) -> dict[str, Any]:
        """Tiếp nhận câu hỏi từ người dùng và trả về phản hồi thông minh."""
        clean_query = user_query.strip()
        if not clean_query:
            return {"answer": "Vui lòng nhập câu hỏi về nhật ký an ninh hoặc trạng thái camera.", "data": {}}

        # 1. Chống Prompt Injection & Jailbreak Attack
        if self._is_prompt_injection(clean_query):
            logger.warning("Prompt injection attempt detected: %s", clean_query)
            return {"answer": SECURITY_VIOLATION_REJECTION, "data": {"security_violation": True}}

        # 2. Kiểm tra Domain Guardrail (Phạm vi an ninh)
        if not self._is_in_domain(clean_query):
            return {"answer": OUT_OF_SCOPE_REJECTION, "data": {"rejected": True}}

        if self.api_key:
            try:
                return await self._answer_with_llm(clean_query)
            except Exception as exc:
                logger.warning("LLM Q&A failed (%s); switching to deterministic intent fallback", exc)

        return await self._answer_with_fallback(clean_query)

    @staticmethod
    def _is_prompt_injection(query: str) -> bool:
        q_lower = query.lower()
        return any(pat in q_lower for pat in PROMPT_INJECTION_PATTERNS)

    @staticmethod
    def _is_in_domain(query: str) -> bool:

        q_lower = query.lower()
        return any(kw in q_lower for kw in DOMAIN_KEYWORDS)

    async def _answer_with_llm(self, query: str) -> dict[str, Any]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key, timeout=10.0)

        messages = [
            {
                "role": "system",
                "content": (
                    "Bạn là Trợ lý An ninh GuardianCam. Bạn CHỈ trả lời các câu hỏi liên quan đến hệ thống "
                    "an ninh gia đình, giám sát camera, sự cố té ngã, người lạ và người thân. "
                    "Nếu câu hỏi KHÔNG liên quan đến các chủ đề này (ví dụ: thời tiết, nấu ăn, lập trình, kiến thức chung...), "
                    "hãy lịch sự từ chối trả lời. Sử dụng các công cụ được cung cấp để đọc dữ liệu chính xác từ SQLite. "
                    "Trả lời ngắn gọn, rõ ràng, lịch sự bằng tiếng Việt."
                ),
            },
            {"role": "user", "content": query},
        ]

        tools = QATools.definitions()
        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )

        message = response.choices[0].message
        collected_data = {}

        if message.tool_calls:
            messages.append(message)
            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments or "{}")

                result = self._execute_tool(func_name, func_args)
                collected_data[func_name] = result

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            final_response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
            answer_text = final_response.choices[0].message.content or "Đã truy vấn dữ liệu an ninh thành công."
        else:
            answer_text = message.content or "Không tìm thấy dữ liệu liên quan."

        return {"answer": answer_text, "data": collected_data}

    async def _answer_with_fallback(self, query: str) -> dict[str, Any]:
        q_lower = query.lower()
        collected_data = {}
        answer_parts = []

        # 1. Sự cố té ngã
        if any(kw in q_lower for kw in ["té ngã", "ngã", "fall"]):
            falls = await asyncio.to_thread(QATools.get_recent_incidents, incident_type="fall", limit=5)
            collected_data["fall_incidents"] = falls
            if falls:
                fall_lines = [
                    f"• Té ngã tại {f['camera_name']} lúc {format_datetime(f['opened_at'])} (Trạng thái: {f['status']})" for f in falls
                ]
                answer_parts.append(f"Ghi nhận {len(falls)} sự cố nghi ngờ té ngã gần nhất:\n" + "\n".join(fall_lines))
            else:
                answer_parts.append("Không có sự cố té ngã nào gần đây trong hệ thống.")

        # 2. Phát hiện người lạ
        elif any(kw in q_lower for kw in ["người lạ", "lạ", "stranger", "unknown"]):
            strangers = await asyncio.to_thread(QATools.get_recent_incidents, incident_type="unknown_person", limit=5)
            collected_data["stranger_incidents"] = strangers
            if strangers:
                stranger_lines = [
                    f"• Người lạ xuất hiện {s['occurrence_count']} lần tại {s['camera_name']} ({s['location_label']}) lúc {format_datetime(s['opened_at'])}" for s in strangers
                ]
                answer_parts.append(f"Ghi nhận {len(strangers)} sự cố phát hiện người lạ gần nhất:\n" + "\n".join(stranger_lines))
            else:
                answer_parts.append("Không phát hiện người lạ nào gần đây trong hệ thống.")

        # 3. Trạng thái camera
        elif any(kw in q_lower for kw in ["camera", "thiết bị", "luồng"]):
            cams = await asyncio.to_thread(QATools.get_camera_status)
            collected_data["cameras"] = cams
            if cams:
                cam_str = ", ".join([f"{c['name']} ({c['operational_status']})" for c in cams])
                answer_parts.append(f"Hệ thống hiện có {len(cams)} camera: {cam_str}.")
            else:
                answer_parts.append("Hệ thống chưa ghi nhận camera nào.")

        # 4. Tóm tắt tổng quan sự cố / Nhật ký sự cố
        elif any(kw in q_lower for kw in ["tóm tắt", "sự cố", "nhật ký"]):
            incidents = await asyncio.to_thread(QATools.get_recent_incidents, limit=5)
            collected_data["recent_incidents"] = incidents
            if incidents:
                inc_lines = []
                for idx, inc in enumerate(incidents, start=1):
                    type_str = "Té ngã" if inc["incident_type"] == "fall" else "Người lạ"
                    sev_str = (inc.get("alert_severity") or "medium").upper()
                    inc_lines.append(
                        f"🔹 {idx}. [{type_str} - {sev_str}]\n   • Vị trí: {inc['camera_name']} ({inc['location_label']})\n   • Thời gian: {format_datetime(inc['opened_at'])}\n   • Trạng thái: {inc['status']} (Ghi nhận {inc['occurrence_count']} lần)"
                    )
                answer_parts.append("📋 TÓM TẮT SỰ CỐ GẦN NHẤT:\n\n" + "\n\n".join(inc_lines))
            else:
                answer_parts.append("Hệ thống chưa ghi nhận sự cố té ngã hoặc người lạ nào trong nhật ký an ninh.")


        # 5. Danh sách người thân
        elif any(kw in q_lower for kw in ["người thân", "danh tính", "thành viên", "gia đình"]):
            persons = await asyncio.to_thread(QATools.get_registered_persons)
            collected_data["registered_persons"] = persons
            if persons:
                p_names = ", ".join([p["display_name"] for p in persons])
                answer_parts.append(f"Danh sách người thân đã đăng ký ({len(persons)} người): {p_names}.")
            else:
                answer_parts.append("Chưa có thông tin người thân nào được đăng ký trong danh bạ gia đình.")

        # 6. Mặc định cho lời chào hỏi
        else:
            cams = await asyncio.to_thread(QATools.get_camera_status)
            incidents = await asyncio.to_thread(QATools.get_recent_incidents, limit=5)
            collected_data["cameras"] = cams
            collected_data["recent_incidents"] = incidents
            answer_parts.append(
                f"Trợ lý GuardianCam xin chào! Hệ thống đang quản lý {len(cams)} camera và {len(incidents)} sự cố trong nhật ký an ninh. Bạn cần tôi hỗ trợ kiểm tra thông tin gì?"
            )

        return {"answer": "\n\n".join(answer_parts), "data": collected_data}


    @staticmethod
    def _execute_tool(name: str, args: dict[str, Any]) -> Any:
        if name == "query_events_summary":
            return QATools.get_events_summary(
                event_type=args.get("event_type", "all"), limit=args.get("limit", 10)
            )
        if name == "query_recent_incidents":
            return QATools.get_recent_incidents(
                incident_type=args.get("incident_type", "all"),
                status=args.get("status", "all"),
                limit=args.get("limit", 10),
            )
        if name == "query_camera_status":
            return QATools.get_camera_status()
        if name == "query_registered_persons":
            return QATools.get_registered_persons()
        return {}
