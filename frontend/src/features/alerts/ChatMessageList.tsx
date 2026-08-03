import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import type { AlertEvent, ChatMessage } from "./alert.types";
import { ChatMessageBubble } from "./ChatMessageBubble";
import { TypingIndicator } from "./TypingIndicator";
export function ChatMessageList({ messages, alert, typing, onExpand, onCloseCamera, onHelpAction, contextualActions }: { messages: ChatMessage[]; alert: AlertEvent; typing: boolean; onExpand: () => void; onCloseCamera: () => void; onHelpAction: (label: string) => void; contextualActions?: ReactNode }) {
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const list = listRef.current;
    if (!list || list.offsetParent === null) return;
    list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
  }, [messages, typing]);
  return <div className="chat-message-list" ref={listRef}>{messages.map((message) => <ChatMessageBubble key={message.id} message={message} alert={alert} onExpand={onExpand} onCloseCamera={onCloseCamera} onHelpAction={onHelpAction} />)}{typing && <div className="chat-row assistant"><span className="assistant-mini">AT</span><TypingIndicator /></div>}{contextualActions}</div>;
}
