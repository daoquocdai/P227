import { X } from "lucide-react";
import type { AlertEvent } from "./alert.types";
import { formatAlertDateTime } from "./alertDateTime";
export function SnapshotModal({ alert, onClose }: { alert: AlertEvent; onClose: () => void }) { return <div className="snapshot-modal-backdrop" onClick={onClose}><div className="snapshot-modal" onClick={(event) => event.stopPropagation()}><button onClick={onClose}><X /></button><div className="snapshot-scene large">{alert.snapshotUrl ? <img src={alert.snapshotUrl} alt={`Ảnh cảnh báo tại ${alert.location}`} /> : <><span className="room-window" /><span className="room-bed" /><span className="person-shape" /></>}</div><div><strong>{alert.location}</strong><span>{alert.subject} · {formatAlertDateTime(alert.occurredAt)}</span></div></div></div>; }
