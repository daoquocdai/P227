import { AlertTriangle, CameraOff, DoorOpen, PersonStanding, UserRoundCheck } from "lucide-react";
import type { AlertEvent } from "./alert.types";
import { formatAlertDateTime } from "./alertDateTime";

const icons = { fall: AlertTriangle, inactivity: PersonStanding, stranger: DoorOpen, camera: CameraOff, arrival: UserRoundCheck };
const statusLabels: Record<AlertEvent["status"], string> = { pending: "Chờ xử lý", checking: "Đang kiểm tra", resolved: "Đã xử lý", safe: "An toàn", false_alarm: "Cảnh báo sai", need_help: "Cần hỗ trợ" };

export function AlertListItem({ alert, selected, onSelect }: { alert: AlertEvent; selected: boolean; onSelect: () => void }) {
  const Icon = icons[alert.type];
  return <button className={`alert-list-item severity-${alert.severity} ${selected ? "selected" : ""}`} onClick={onSelect}>
    <span className="alert-list-icon"><Icon /></span>
    <span className="alert-item-copy">
      <span className="alert-item-title"><strong>{alert.title}</strong><time dateTime={alert.occurredAt}>{formatAlertDateTime(alert.occurredAt)}</time></span>
      <span className="alert-item-meta">{alert.subject} · {alert.location}</span>
      <span className="alert-item-preview">{alert.preview}</span>
      <span className={`alert-status status-${alert.status}`}>{statusLabels[alert.status]}</span>
    </span>
    {alert.unread && <span className="alert-unread" aria-label="Chưa đọc" />}
  </button>;
}
