import type { ChatMessage, MessageContentType, QuickAction } from "./alert.types";

const whyText = `Tôi đưa ra cảnh báo vì nhận thấy ba dấu hiệu:\n\n1. Tư thế cơ thể thay đổi nhanh từ đứng sang nằm.\n2. Người trong khung hình nằm gần mặt sàn.\n3. Không có chuyển động rõ ràng trong khoảng 12 giây.\n\nKhả năng xảy ra té ngã được đánh giá ở mức khá cao, nhưng bạn vẫn là người xác nhận cuối cùng.`;

export function detectIntent(text: string): MessageContentType {
  const value = text.toLocaleLowerCase("vi");
  if (/tại sao|vì sao|lý do|tự tin|độ tin cậy|91%/.test(value)) return "confidence";
  if (/ảnh|hình/.test(value)) return "snapshot";
  if (/camera|trực tiếp/.test(value)) return "camera";
  if (/an toàn|ổn rồi/.test(value)) return "success";
  if (/giúp|hỗ trợ|khẩn cấp/.test(value)) return "help";
  return "text";
}

export function responseFor(contentType: MessageContentType, subject: string, location: string): string {
  if (contentType === "confidence") return whyText;
  if (contentType === "snapshot") return "Đây là hình ảnh tại thời điểm cảnh báo được ghi nhận.";
  if (contentType === "camera") return `Tôi đang mở camera ${location} để bạn kiểm tra.`;
  if (contentType === "success") return `Tôi có thể giúp bạn xác nhận ${subject} hiện an toàn.`;
  if (contentType === "help") return "Tôi đã ghi nhận đây là tình huống cần hỗ trợ. Bạn muốn thực hiện bước nào tiếp theo?";
  return "Tôi có thể giúp bạn xem hình ảnh, mở camera, giải thích lý do cảnh báo hoặc cập nhật trạng thái sự kiện.";
}

export function actionContentType(action: QuickAction["id"]): MessageContentType {
  return action === "why" ? "confidence" : action === "safe" ? "success" : action;
}

export const waitForAssistant = () => new Promise<void>((resolve) => window.setTimeout(resolve, 800));
export const newMessage = (role: ChatMessage["role"], text: string, contentType: MessageContentType): ChatMessage => ({ id: `${role}-${Date.now()}-${Math.random()}`, role, text, contentType, createdAt: new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }) });
