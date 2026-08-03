import { CheckCircle2 } from "lucide-react";
import type { AlertEvent, ChatMessage } from "./alert.types";
import { CameraPreviewCard } from "./CameraPreviewCard";
import { ConfidenceCard } from "./ConfidenceCard";
import { EventDetailCard } from "./EventDetailCard";
import { NeedHelpActions } from "./NeedHelpActions";
import { SnapshotCard } from "./SnapshotCard";

export function ChatMessageBubble({ message, alert, onExpand, onCloseCamera, onHelpAction, onSafe, onFalseAlarm }: { message: ChatMessage; alert: AlertEvent; onExpand: () => void; onCloseCamera: () => void; onHelpAction: (label: string) => void; onSafe: () => void; onFalseAlarm: () => void }) {
  if (message.role === "user") return <div className="chat-row user"><div className="chat-bubble">{message.text}</div></div>;
  return <div className={`chat-row assistant content-${message.contentType}`}><span className="assistant-mini">AT</span><div className={`assistant-message message-${message.contentType}`}><div className="chat-bubble preserve-lines">{message.text}</div>
    {message.contentType === "event" && <EventDetailCard alert={alert} onExpand={onExpand} onSafe={onSafe} onFalseAlarm={onFalseAlarm} />}
    {message.contentType === "snapshot" && <SnapshotCard alert={alert} onExpand={onExpand} />}
    {message.contentType === "camera" && <CameraPreviewCard alert={alert} onClose={onCloseCamera} onExpand={onExpand} />}
    {message.contentType === "confidence" && <ConfidenceCard />}
    {message.contentType === "success" && alert.status === "safe" && <div className="success-card"><CheckCircle2 /><div><b>Người thân đã an toàn</b><span>Người xác nhận: Minh Nguyễn · {new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}</span></div></div>}
    {message.contentType === "help" && <NeedHelpActions onAction={onHelpAction} />}
  </div></div>;
}
