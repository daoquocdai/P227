import { Clock3 } from "lucide-react";
import type { AlertEvent } from "./alert.types";
import { formatAlertDateTime } from "./alertDateTime";
const labels: Record<AlertEvent["status"], string> = { pending: "Đang chờ bạn xác nhận", checking: "Đang kiểm tra", resolved: "Đã xử lý", safe: "Đã xác nhận an toàn", false_alarm: "Cảnh báo sai", need_help: "Đang cần hỗ trợ" };
const mobileLabels: Record<AlertEvent["status"], string> = { pending: "Chờ xác nhận", checking: "Đang kiểm tra", resolved: "Đã xử lý", safe: "An toàn", false_alarm: "Cảnh báo sai", need_help: "Cần hỗ trợ" };
export function AlertSummaryBanner({ alert }: { alert: AlertEvent }) { return <div className={`alert-summary severity-${alert.severity}`}><div><strong>{alert.title}</strong><span>{alert.subject} · {alert.location} · <time dateTime={alert.occurredAt}>{formatAlertDateTime(alert.occurredAt)}</time></span></div><span className={`alert-status status-${alert.status}`}><Clock3 /><span className="summary-status-desktop">{labels[alert.status]}</span><span className="summary-status-mobile">{mobileLabels[alert.status]}</span></span></div>; }
