import { Send, X } from "lucide-react";
import { useState } from "react";
export function ChatInput({ disabled, onSend, onClose }: { disabled: boolean; onSend: (text: string) => void; onClose?: () => void }) {
  const [value, setValue] = useState("");
  const submit = () => { const text = value.trim(); if (!text || disabled) return; onSend(text); setValue(""); };
  return <div className="chat-input-wrap copilot-composer">{onClose&&<button className="composer-close" onClick={onClose} aria-label="Đóng ô nhập"><X/></button>}<textarea autoFocus rows={1} value={value} disabled={disabled} placeholder="Hỏi An Tâm về cảnh báo này..." onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }} /><button className="composer-send" disabled={disabled || !value.trim()} onClick={submit} aria-label="Gửi"><Send /></button></div>;
}
