import { ImageOff, ShieldCheck } from "lucide-react";
import type { AlertEvent } from "./alert.types";
import { formatAlertDateTime } from "./alertDateTime";
import "./snapshot.css";

export function SnapshotCard({ alert, onExpand }: { alert: AlertEvent; onExpand: () => void }) {
  const content = <>
    <span className="snapshot-scene">{alert.snapshotUrl ? <img src={alert.snapshotUrl} alt={`Ảnh cảnh báo tại ${alert.location}`} /> : <span className="snapshot-missing"><ImageOff /><strong>Không có ảnh bằng chứng</strong></span>}</span>
    <span className="snapshot-top"><b>{alert.location}</b><time dateTime={alert.occurredAt}>{formatAlertDateTime(alert.occurredAt)}</time></span>
    <span className="snapshot-bottom"><span><ShieldCheck /> Xử lý cục bộ trên Local Hub</span></span>
  </>;
  return alert.snapshotUrl
    ? <button className="snapshot-card" onClick={onExpand} aria-label="Phóng to ảnh cảnh báo">{content}</button>
    : <div className="snapshot-card snapshot-card-missing">{content}</div>;
}
