import { ShieldCheck } from "lucide-react";
import type { AlertEvent } from "./alert.types";
import { formatAlertDateTime } from "./alertDateTime";

export function SnapshotCard({ alert, onExpand }: { alert: AlertEvent; onExpand: () => void }) {
  return <button className="snapshot-card" onClick={onExpand} aria-label="Phóng to ảnh cảnh báo">
    <span className="snapshot-scene">{alert.snapshotUrl ? <img src={alert.snapshotUrl} alt={`Ảnh cảnh báo tại ${alert.location}`} /> : <><span className="room-window" /><span className="room-bed" /><span className="person-shape" /></>}</span>
    <span className="snapshot-top"><b>{alert.location}</b><time dateTime={alert.occurredAt}>{formatAlertDateTime(alert.occurredAt)}</time></span>
    <span className="snapshot-bottom"><span><ShieldCheck /> Được xử lý cục bộ · Nhấn để xem ảnh</span></span>
  </button>;
}
