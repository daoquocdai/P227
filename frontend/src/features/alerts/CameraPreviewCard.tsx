import { Expand, Video, X } from "lucide-react";
import type { AlertEvent } from "./alert.types";
export function CameraPreviewCard({ alert, onClose, onExpand }: { alert: AlertEvent; onClose: () => void; onExpand: () => void }) {
  return <div className="camera-preview-card"><div className="camera-scene"><span className="room-window" /><span className="room-bed" /><span className="person-shape upright" /><span className="live-badge">LIVE</span></div>
    <div className="camera-preview-bar"><span><Video /><b>{alert.location}</b><small>Online</small></span><button onClick={onExpand} aria-label="Toàn màn hình"><Expand /></button><button onClick={onClose} aria-label="Đóng camera"><X /></button></div>
    <p>Video được xử lý cục bộ, không gửi lên cloud.</p></div>;
}

