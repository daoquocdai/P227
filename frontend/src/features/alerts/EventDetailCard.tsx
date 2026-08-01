import type { AlertEvent } from "./alert.types";
import { SnapshotCard } from "./SnapshotCard";
import { formatAlertDateTime } from "./alertDateTime";

export function EventDetailCard({ alert, onExpand }: { alert: AlertEvent; onExpand: () => void }) {
  return <article className="event-detail-card">
    <header className="event-case-header"><div><p className="event-kicker">AI vừa phát hiện một tình huống</p><h3>{alert.title}</h3><span>{alert.subject} · {alert.location} · {formatAlertDateTime(alert.occurredAt)}</span></div><b>Đang chờ xác nhận</b></header>
    <SnapshotCard alert={alert} onExpand={onExpand} />
    <section className="event-ai-analysis"><strong>Phân tích của An Tâm</strong><p>Tôi nhận thấy người trong khung hình chuyển từ tư thế đứng sang nằm.</p><p>Sau đó chưa phát hiện chuyển động rõ ràng trong khoảng {alert.immobileSeconds ?? 12} giây.</p><p>Bạn nên kiểm tra hình ảnh trước khi xác nhận.</p></section>
    <section className="event-insight"><h4>Phân tích nhanh</h4><div><span>Khả năng<strong>{alert.confidence ?? 91}%</strong></span><span>Người<strong>{alert.subject}</strong></span><span>Camera<strong>{alert.location}</strong></span><span>Thời gian<strong>{formatAlertDateTime(alert.occurredAt)}</strong></span></div></section>
    <div className="event-mobile-meta event-meta"><span>{alert.confidence ?? 91}% khả năng</span><span>{alert.subject}</span><span>{alert.location}</span><span>{formatAlertDateTime(alert.occurredAt)}</span></div>
  </article>;
}
