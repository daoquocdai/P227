import type { AlertEvent, ChatMessage, QuickAction } from "./alert.types";

export const initialAlerts: AlertEvent[] = [
  { id: "fall-lan", cameraId:"camera-bedroom", eventId:"event-fall-lan", occurredAt:"2026-07-30T09:25:10", type: "fall", title: "Có khả năng té ngã", subject: "Bà Lan", location: "Phòng ngủ", time: "09:25", timestamp: "09:25:10", severity: "high", status: "pending", unread: true, preview: "Tôi phát hiện tư thế bất thường và chưa thấy chuyển động.", confidence: 91, immobileSeconds: 12 },
  { id: "stranger-back", cameraId:"camera-entrance", eventId:"event-stranger-back", occurredAt:"2026-07-30T02:15:04", type: "stranger", title: "Có người lạ xuất hiện", subject: "Camera cửa sau", location: "Cửa sau", time: "02:15", timestamp: "02:15:04", severity: "critical", status: "pending", unread: true, preview: "Một người chưa nhận diện xuất hiện tại khu vực cửa sau." },
  { id: "fall-living", cameraId:"camera-living", eventId:"event-fall-living", occurredAt:"2026-07-27T14:05:00", type: "fall", title: "Có khả năng té ngã", subject: "Bà Lan", location: "Phòng khách", time: "3 ngày trước", timestamp: "3 ngày trước, 14:05", severity: "high", status: "false_alarm", unread: false, preview: "Sự kiện đã được đánh dấu là cảnh báo sai." },
];

export const quickActions: QuickAction[] = [
  { id: "camera", label: "Xem camera" }, { id: "snapshot", label: "Xem ảnh" },
  { id: "safe", label: "Tôi đã kiểm tra — An toàn" }, { id: "help", label: "Cần người hỗ trợ" },
  { id: "why", label: "Tại sao có cảnh báo?" }, { id: "false_alarm", label: "Đây là cảnh báo sai" },
];

export function createInitialMessages(alert: AlertEvent): ChatMessage[] {
  return [{ id: `intro-${alert.id}`, role: "assistant", contentType: "event", createdAt: alert.time,
    text: alert.type === "fall" ? "Tôi vừa phát hiện một tình huống có thể cần bạn kiểm tra." : `Tôi đã ghi nhận sự kiện “${alert.title}”. Tôi có thể giúp bạn kiểm tra và xử lý.` }];
}
