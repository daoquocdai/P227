import { Check, ChevronDown, Sparkles, ThumbsDown } from "lucide-react";
import { useState } from "react";
import type { AlertEvent } from "./alert.types";
import { SnapshotCard } from "./SnapshotCard";
import { formatAlertDateTime } from "./alertDateTime";

const statusLabels: Record<AlertEvent["status"], string> = {
  pending: "Chờ xác nhận", checking: "Đang kiểm tra", resolved: "Đã xử lý",
  safe: "Đã xác nhận an toàn", false_alarm: "Cảnh báo sai", need_help: "Cần hỗ trợ",
};

export function EventDetailCard({ alert, onExpand, onSafe, onFalseAlarm }: {
  alert: AlertEvent;
  onExpand: () => void;
  onSafe: () => void;
  onFalseAlarm: () => void;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [busyAction, setBusyAction] = useState<"safe" | "false" | null>(null);
  const terminal = ["safe", "false_alarm", "resolved"].includes(alert.status);
  const invoke = (action: "safe" | "false", callback: () => void) => {
    setBusyAction(action);
    window.setTimeout(() => { callback(); setBusyAction(null); }, 450);
  };

  return <article className={`event-detail-card event-hero severity-${alert.severity}`}>
    <header className="event-case-header"><div><p className="event-kicker">AI VỪA PHÁT HIỆN</p><h3>{alert.title}</h3><span>{alert.subject} · {alert.location} · {formatAlertDateTime(alert.occurredAt)}</span></div><b className={`status-${alert.status}`}>{statusLabels[alert.status]}</b></header>
    <SnapshotCard alert={alert} onExpand={onExpand} />
    <div className="hero-primary-actions">
      <button className={`hero-safe ${alert.status === "safe" ? "is-complete" : ""}`} disabled={terminal || busyAction !== null} onClick={() => invoke("safe", onSafe)}>{alert.status === "safe" ? <><Check /> Đã ghi nhận an toàn</> : busyAction === "safe" ? <><i /> Đang ghi nhận...</> : <><Check /> Tôi đã kiểm tra — An toàn</>}</button>
      <button className="hero-false" disabled={terminal || busyAction !== null} onClick={() => invoke("false", onFalseAlarm)}>{busyAction === "false" ? <><i /> Đang mở...</> : <><ThumbsDown /> Báo sai</>}</button>
    </div>
    <div className="hero-ai-summary"><Sparkles /><p>Tôi nhận thấy người trong khung hình chuyển từ tư thế đứng sang nằm và chưa có chuyển động rõ ràng trong khoảng {alert.immobileSeconds ?? 12} giây.</p></div>
    <button className={`analysis-toggle ${detailsOpen ? "is-open" : ""}`} onClick={() => setDetailsOpen((value) => !value)} aria-expanded={detailsOpen}>Xem chi tiết phân tích <ChevronDown /></button>
    {detailsOpen && <section className="analysis-collapsible">
      <p>Hãy đối chiếu ảnh bằng chứng và tình trạng thực tế trước khi xử lý cảnh báo. Kết quả AI chỉ đóng vai trò hỗ trợ caregiver.</p>
      <div className="event-inline-insights"><span><small>Khả năng</small><strong>{alert.confidence ?? 91}%</strong></span><span><small>Người</small><strong>{alert.subject}</strong></span><span><small>Camera</small><strong>{alert.location}</strong></span><span><small>Thời gian</small><strong>{formatAlertDateTime(alert.occurredAt)}</strong></span></div>
    </section>}
  </article>;
}
