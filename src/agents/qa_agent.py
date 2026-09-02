import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
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


def parse_date_from_query(query: str) -> tuple[str | None, str | None]:
    """
    Trích xuất ngày từ câu hỏi tiếng Việt.
    Trả về (target_date_str_yyyy_mm_dd, display_label) hoặc (None, None).
    """
    q_lower = query.lower().strip()
    today = datetime.now().date()

    if "hôm nay" in q_lower or "hom nay" in q_lower or "today" in q_lower:
        d_str = today.strftime("%Y-%m-%d")
        lbl = f"hôm nay ({today.strftime('%d/%m/%Y')})"
        return d_str, lbl

    if "hôm qua" in q_lower or "hom qua" in q_lower or "yesterday" in q_lower:
        yest = today - timedelta(days=1)
        d_str = yest.strftime("%Y-%m-%d")
        lbl = f"hôm qua ({yest.strftime('%d/%m/%Y')})"
        return d_str, lbl

    if "hôm kia" in q_lower or "hom kia" in q_lower:
        prev = today - timedelta(days=2)
        d_str = prev.strftime("%Y-%m-%d")
        lbl = f"hôm kia ({prev.strftime('%d/%m/%Y')})"
        return d_str, lbl

    # Match DD/MM/YYYY hoặc DD-MM-YYYY
    match_full = re.search(r"(\b\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b", q_lower)
    if match_full:
        day, month, year = int(match_full.group(1)), int(match_full.group(2)), int(match_full.group(3))
        try:
            parsed = datetime(year, month, day).date()
            return parsed.strftime("%Y-%m-%d"), f"ngày {parsed.strftime('%d/%m/%Y')}"
        except ValueError:
            pass

    # Match DD/MM hoặc DD-MM (mặc định lấy năm hiện tại)
    match_short = re.search(r"(?:ngày\s+)?(\b\d{1,2})[/\-](\d{1,2})\b", q_lower)
    if match_short:
        day, month = int(match_short.group(1)), int(match_short.group(2))
        try:
            parsed = datetime(today.year, month, day).date()
            return parsed.strftime("%Y-%m-%d"), f"ngày {parsed.strftime('%d/%m/%Y')}"
        except ValueError:
            pass

    # Match YYYY-MM-DD
    match_iso = re.search(r"\b(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})\b", q_lower)
    if match_iso:
        year, month, day = int(match_iso.group(1)), int(match_iso.group(2)), int(match_iso.group(3))
        try:
            parsed = datetime(year, month, day).date()
            return parsed.strftime("%Y-%m-%d"), f"ngày {parsed.strftime('%d/%m/%Y')}"
        except ValueError:
            pass

    return None, None


def extract_person_name_from_query(query: str) -> tuple[str | None, bool]:
    """
    Trích xuất tên người từ câu hỏi.
    Trả về (person_name, is_registered):
    - (name, True) nếu tên đã được đăng ký trong danh bạ gia đình.
    - (name, False) nếu tên được hỏi nhưng chưa đăng ký trong danh bạ.
    - (None, False) nếu không hỏi tên người cụ thể.
    """
    q_lower = query.lower()
    registered_map: dict[str, str] = {}

    try:
        persons = QATools.get_registered_persons()
        for p in persons:
            d_name = p.get("display_name", "").strip()
            if d_name:
                registered_map[d_name.lower()] = d_name
    except Exception:
        pass

    # 1. Kiểm tra nếu khớp người thân đã đăng ký trong DB
    for r_lower, display in registered_map.items():
        pattern = r"(?<!\w)" + re.escape(r_lower) + r"(?!\w)"
        if re.search(pattern, q_lower):
            return display.title(), True

    # 2. Tìm kiếm tên chưa đăng ký theo các mẫu câu thường gặp
    stop_words = {
        "hôm nay", "hôm qua", "hôm kia", "nào", "ai", "người", "gì", "sự cố", "cảnh báo",
        "camera", "hệ thống", "nhật ký", "tóm tắt", "phòng", "nhà", "sân", "cổng", "bảo vệ",
        "té ngã", "ngã", "té", "người lạ", "lạ", "nguoi la", "stranger", "unknown",
        "thiết bị", "luồng", "trạng thái", "lịch sử", "timeline", "k", "khong", "không"
    }

    # Match pattern: <tên> (có|bị|đang) (ngã|té|xuất hiện|làm|bị ngã)
    match = re.search(
        r"(?:hôm nay|hôm qua|hôm kia)?\s*([a-zàáảãạăằắtẳẵặâầấẩẫậnèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđA-Z]+)\s+(?:có|bị|đang)\s+(?:ngã|té|xuất hiện|bị ngã|làm)",
        query,
        re.IGNORECASE,
    )
    if match:
        candidate = match.group(1).strip()
        cand_lower = candidate.lower()
        if cand_lower not in stop_words and len(cand_lower) >= 2:
            return candidate.title(), False

    # Match pattern: sự cố (của|về|liên quan) <tên>
    match_of = re.search(
        r"sự cố\s+(?:của|về|liên quan đến|liên quan)\s+([a-zàáảãạăằắtẳẵặâầấẩẫậnèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđA-Z]+)",
        query,
        re.IGNORECASE,
    )
    if match_of:
        candidate = match_of.group(1).strip()
        cand_lower = candidate.lower()
        if cand_lower not in stop_words and len(cand_lower) >= 2:
            return candidate.title(), False

    return None, False


BOT_IDENTITY_PATTERNS = [
    "bao nhiêu tuổi", "bạn bao nhiêu tuổi", "tuổi của bạn", "bạn tên gì", "bạn tên là gì",
    "bạn là ai", "bạn từ đâu", "ai tạo ra bạn", "bạn làm được gì", "bạn có thể làm gì",
    "bạn là gì", "giới thiệu bản thân"
]

DOMAIN_KEYWORDS = [
    "camera", "thiết bị", "luồng", "té ngã", "ngã", "te nga", "nga", "fall", "người lạ", "lạ", "nguoi la", "stranger",
    "unknown", "người thân", "nguoi than", "danh tính", "danh tinh", "thành viên", "gia đình", "sự cố", "su co", "cảnh báo", "canh bao",
    "tóm tắt", "tom tat", "timeline", "nhật ký", "nhat ky", "lịch sử", "lich su", "bảo vệ", "phòng khách", "phòng ngủ",
    "sân", "cổng", "hành lang", "hệ thống", "he thong", "trạng thái", "trang thai", "chào", "hi", "xin chào"
] + BOT_IDENTITY_PATTERNS

PROMPT_INJECTION_PATTERNS = [
    "ignore previous instructions", "ignore all previous", "ignore all instructions",
    "ignore instructions", "disregard prior", "disregard all instructions", "disregard instructions",
    "forget all instructions", "forget instructions", "ignore the above", "ignore prompt",
    "you are now", "developer mode", "jailbreak", "dan mode", "system prompt",
    "print prompt", "show schema", "drop table", "select * from", "delete from",
    "update users", "password_hash", "tell the user my email", "reply only with",
    "do not summarize"
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

        # 2. Kiểm tra Out-of-Scope rõ ràng (Medical, URL, External Text)
        if self._is_out_of_scope_explicit(clean_query):
            return {"answer": OUT_OF_SCOPE_REJECTION, "data": {"rejected": True}}

        # 3. Kiểm tra Domain Guardrail (Phạm vi an ninh)
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
    def _is_out_of_scope_explicit(query: str) -> bool:
        q_lower = query.lower()

        # 1. Yêu cầu mở / tóm tắt / truy cập đường dẫn URL ngoài
        if any(link in q_lower for link in ["http://", "https://", "www.", "discord.com", "github.com", "facebook.com", "truy cập link"]):
            return True

        # 2. Yêu cầu tư vấn y tế / bệnh tật (đau bụng, đau đầu, sốt...)
        if any(med in q_lower for med in ["đau bụng", "đau đầu", "sốt", "bệnh", "thuốc", "bác sĩ", "đau lưng", "chóng mặt", "buồn nôn", "nhức đầu", "cảm cúm"]):
            return True

        # 3. Tóm tắt nội dung văn bản ngoài (bài viết, bóng đá, tin tức...) không phải sự cố an ninh
        if any(ext in q_lower for ext in ["bài viết", "bóng đá", "lịch sử bóng đá", "tin tức", "văn bản"]):
            if not any(sec in q_lower for sec in ["sự cố", "té ngã", "người lạ", "camera", "nhật ký"]):
                return True

        return False

    @staticmethod
    def _is_in_domain(query: str) -> bool:
        q_lower = query.lower()
        for kw in DOMAIN_KEYWORDS:
            # Dùng regex word boundary để tránh trùng khớp từ con (vd: "hi" trong "nhiêu", "lạ" trong "lại")
            pattern = r"(?<!\w)" + re.escape(kw) + r"(?!\w)"
            if re.search(pattern, q_lower):
                return True
        return False

    async def _answer_with_llm(self, query: str) -> dict[str, Any]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key, timeout=10.0)

        today_str = datetime.now().strftime("%Y-%m-%d")
        today_vn = datetime.now().strftime("%d/%m/%Y")

        messages = [
            {
                "role": "system",
                "content": (
                    "Bạn là Trợ lý An ninh GuardianCam. Bạn CHỈ trả lời các câu hỏi liên quan đến hệ thống "
                    "an ninh gia đình, giám sát camera, sự cố té ngã, người lạ và người thân. "
                    f"Thời gian hiện tại của hệ thống: Ngày {today_vn} ({today_str}). "
                    "Nếu người dùng hỏi về một ngày cụ thể (ví dụ: hôm nay, hôm qua, ngày 23/08...), hãy quy đổi thành ngày YYYY-MM-DD "
                    "và truyền tham số `date` vào công cụ tương ứng (query_recent_incidents / query_events_summary). "
                    "Nếu người dùng hỏi về một người thân cụ thể (ví dụ: 'Mạnh', 'Bà Nội'...), hãy truyền tên người đó vào tham số `person_name` "
                    "của công cụ `query_recent_incidents`. "
                    "Nếu người thân chưa được đăng ký trong danh bạ, hãy trả lời đúng dạng: 'Người thân tên [Tên] chưa được đăng ký trong danh bạ gia đình. Hãy đăng ký ở mục \"Người thân\"'. "
                    "Không được tự ý liệt kê danh sách tên những người thân khác để bảo vệ thông tin riêng tư. "
                    "Nếu ngày đó có ít hơn hoặc bằng 5 sự cố, liệt kê toàn bộ các sự cố của ngày đó. "
                    "Nếu có nhiều hơn 5 sự cố trong ngày đó, chỉ đưa ra 5 sự cố mới nhất của ngày đó. "
                    "Nếu câu hỏi KHÔNG liên quan đến các chủ đề này, hãy lịch sự từ chối trả lời. "
                    "Sử dụng các công cụ được cung cấp để đọc dữ liệu chính xác từ SQLite. Trả lời ngắn gọn, rõ ràng, lịch sự bằng tiếng Việt."
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
        target_date, date_label = parse_date_from_query(query)
        person_name, is_registered = extract_person_name_from_query(query)

        # Kiểm tra nếu hỏi tên người chưa đăng ký trong danh bạ -> Bảo mật & thông báo ngắn
        if person_name and not is_registered:
            return {
                "answer": f'Người thân tên {person_name} chưa được đăng ký trong danh bạ gia đình. Hãy đăng ký ở mục "Người thân".',
                "data": {"unregistered_person": person_name},
            }

        # 0. Câu hỏi về bản thân Agent (Tên, tuổi, vai trò)
        if any(pat in q_lower for pat in BOT_IDENTITY_PATTERNS):
            return {
                "answer": (
                    "Tôi là Trợ lý An ninh AI GuardianCam! Tôi không có tuổi như con người, nhưng tôi hoạt động 24/7 "
                    "để hỗ trợ bạn giám sát camera, cảnh báo té ngã và phát hiện người lạ trong gia đình."
                ),
                "data": {},
            }

        # 1. Sự cố té ngã
        if any(kw in q_lower for kw in ["té ngã", "ngã", "fall"]):
            fetch_limit = 50 if (target_date or person_name) else 5
            falls = await asyncio.to_thread(
                QATools.get_recent_incidents,
                incident_type="fall",
                limit=fetch_limit,
                date=target_date,
                person_name=person_name,
            )
            total_count = len(falls)
            display_falls = falls[:5]
            collected_data["fall_incidents"] = display_falls

            p_prefix = f" liên quan đến {person_name}" if person_name else ""

            if target_date:
                if total_count == 0:
                    answer_parts.append(f"Không có sự cố té ngã nào{p_prefix} được ghi nhận {date_label} trong hệ thống.")
                elif total_count <= 5:
                    fall_lines = [
                        f"• Té ngã tại {f['camera_name']} lúc {format_datetime(f['opened_at'])} (Trạng thái: {f['status']})"
                        for f in display_falls
                    ]
                    answer_parts.append(f"Ghi nhận {total_count} sự cố nghi ngờ té ngã{p_prefix} {date_label}:\n" + "\n".join(fall_lines))
                else:
                    fall_lines = [
                        f"• Té ngã tại {f['camera_name']} lúc {format_datetime(f['opened_at'])} (Trạng thái: {f['status']})"
                        for f in display_falls
                    ]
                    answer_parts.append(
                        f"Ghi nhận 5 sự cố nghi ngờ té ngã gần nhất{p_prefix} {date_label} (trong tổng số {total_count} sự cố):\n"
                        + "\n".join(fall_lines)
                    )
            else:
                if display_falls:
                    fall_lines = [
                        f"• Té ngã tại {f['camera_name']} lúc {format_datetime(f['opened_at'])} (Trạng thái: {f['status']})"
                        for f in display_falls
                    ]
                    answer_parts.append(f"Ghi nhận {len(display_falls)} sự cố nghi ngờ té ngã{p_prefix} gần nhất:\n" + "\n".join(fall_lines))
                else:
                    answer_parts.append(f"Không có sự cố té ngã nào{p_prefix} gần đây trong hệ thống.")

        # 2. Phát hiện người lạ
        elif any(kw in q_lower for kw in ["người lạ", "lạ", "stranger", "unknown"]):
            fetch_limit = 50 if target_date else 5
            strangers = await asyncio.to_thread(
                QATools.get_recent_incidents, incident_type="unknown_person", limit=fetch_limit, date=target_date
            )
            total_count = len(strangers)
            display_strangers = strangers[:5]
            collected_data["stranger_incidents"] = display_strangers

            if target_date:
                if total_count == 0:
                    answer_parts.append(f"Không phát hiện người lạ nào {date_label} trong hệ thống.")
                elif total_count <= 5:
                    stranger_lines = [
                        f"• Người lạ xuất hiện {s['occurrence_count']} lần tại {s['camera_name']} ({s['location_label']}) lúc {format_datetime(s['opened_at'])}"
                        for s in display_strangers
                    ]
                    answer_parts.append(f"Ghi nhận {total_count} sự cố phát hiện người lạ {date_label}:\n" + "\n".join(stranger_lines))
                else:
                    stranger_lines = [
                        f"• Người lạ xuất hiện {s['occurrence_count']} lần tại {s['camera_name']} ({s['location_label']}) lúc {format_datetime(s['opened_at'])}"
                        for s in display_strangers
                    ]
                    answer_parts.append(
                        f"Ghi nhận 5 sự cố phát hiện người lạ gần nhất {date_label} (trong tổng số {total_count} sự cố):\n"
                        + "\n".join(stranger_lines)
                    )
            else:
                if display_strangers:
                    stranger_lines = [
                        f"• Người lạ xuất hiện {s['occurrence_count']} lần tại {s['camera_name']} ({s['location_label']}) lúc {format_datetime(s['opened_at'])}"
                        for s in display_strangers
                    ]
                    answer_parts.append(f"Ghi nhận {len(display_strangers)} sự cố phát hiện người lạ gần nhất:\n" + "\n".join(stranger_lines))
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
            fetch_limit = 50 if (target_date or person_name) else 5
            incidents = await asyncio.to_thread(
                QATools.get_recent_incidents, limit=fetch_limit, date=target_date, person_name=person_name
            )
            total_count = len(incidents)
            display_incidents = incidents[:5]
            collected_data["recent_incidents"] = display_incidents

            p_prefix = f" liên quan đến {person_name}" if person_name else ""

            if target_date:
                if total_count == 0:
                    answer_parts.append(f"Hệ thống không ghi nhận sự cố nào{p_prefix} {date_label}.")
                else:
                    inc_lines = []
                    for idx, inc in enumerate(display_incidents, start=1):
                        type_str = "Té ngã" if inc["incident_type"] == "fall" else "Người lạ"
                        sev_str = (inc.get("alert_severity") or "medium").upper()
                        inc_lines.append(
                            f"🔹 {idx}. [{type_str} - {sev_str}]\n   • Vị trí: {inc['camera_name']} ({inc['location_label']})\n   • Thời gian: {format_datetime(inc['opened_at'])}\n   • Trạng thái: {inc['status']} (Ghi nhận {inc['occurrence_count']} lần)"
                        )
                    header_suffix = f" ({total_count} SỰ CỐ):" if total_count <= 5 else f" (5/{total_count} SỰ CỐ MỚI NHẤT):"
                    answer_parts.append(f"📋 TÓM TẮT SỰ CỐ{p_prefix.upper()} {date_label.upper()}{header_suffix}\n\n" + "\n\n".join(inc_lines))
            else:
                if display_incidents:
                    inc_lines = []
                    for idx, inc in enumerate(display_incidents, start=1):
                        type_str = "Té ngã" if inc["incident_type"] == "fall" else "Người lạ"
                        sev_str = (inc.get("alert_severity") or "medium").upper()
                        inc_lines.append(
                            f"🔹 {idx}. [{type_str} - {sev_str}]\n   • Vị trí: {inc['camera_name']} ({inc['location_label']})\n   • Thời gian: {format_datetime(inc['opened_at'])}\n   • Trạng thái: {inc['status']} (Ghi nhận {inc['occurrence_count']} lần)"
                        )
                    answer_parts.append(f"📋 TÓM TẮT SỰ CỐ{p_prefix.upper()} GẦN NHẤT:\n\n" + "\n\n".join(inc_lines))
                else:
                    answer_parts.append(f"Hệ thống chưa ghi nhận sự cố té ngã hoặc người lạ nào{p_prefix} trong nhật ký an ninh.")

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
            answer_parts.append(
                "Trợ lý GuardianCam xin chào! Bạn cần tôi hỗ trợ kiểm tra thông tin gì về camera, sự cố té ngã hay người lạ không?"
            )

        return {"answer": "\n\n".join(answer_parts), "data": collected_data}

    @staticmethod
    def _execute_tool(name: str, args: dict[str, Any]) -> Any:
        if name == "query_events_summary":
            return QATools.get_events_summary(
                event_type=args.get("event_type", "all"),
                limit=args.get("limit", 10),
                date=args.get("date"),
            )
        if name == "query_recent_incidents":
            return QATools.get_recent_incidents(
                incident_type=args.get("incident_type", "all"),
                status=args.get("status", "all"),
                limit=args.get("limit", 10),
                date=args.get("date"),
                person_name=args.get("person_name"),
            )
        if name == "query_camera_status":
            return QATools.get_camera_status()
        if name == "query_registered_persons":
            return QATools.get_registered_persons()
        return {}
