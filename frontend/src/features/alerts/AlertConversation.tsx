import { useEffect, useState } from "react";
import type { AlertEvent, ChatMessage, MessageContentType, QuickAction } from "./alert.types";
import { createInitialMessages } from "./alertMockData";
import { actionContentType, newMessage, responseFor, waitForAssistant } from "./assistantMockEngine";
import { AlertConversationHeader } from "./AlertConversationHeader";
import { AlertSummaryBanner } from "./AlertSummaryBanner";
import { ChatMessageList } from "./ChatMessageList";
import { ConfirmSafeModal } from "./ConfirmSafeModal";
import { FalseAlarmForm } from "./FalseAlarmForm";
import { QuickActionList } from "./QuickActionList";
import { SnapshotModal } from "./SnapshotModal";

export function AlertConversation({ alert, onBack, onStatus }: { alert: AlertEvent; onBack: () => void; onStatus: (status: AlertEvent["status"]) => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>(() => createInitialMessages(alert)); const [typing, setTyping] = useState(false); const [safeModal, setSafeModal] = useState(false); const [falseModal, setFalseModal] = useState(false); const [snapshotModal, setSnapshotModal] = useState(false);
  useEffect(() => { setMessages(createInitialMessages(alert)); setTyping(false); }, [alert.id]);
  const respond = async (userText: string, contentType: MessageContentType) => { setMessages((items) => [...items, newMessage("user", userText, "text")]); if (contentType === "success") { setSafeModal(true); return; } if (contentType === "false_alarm") { setFalseModal(true); return; } setTyping(true); await waitForAssistant(); setTyping(false); setMessages((items) => [...items, newMessage("assistant", responseFor(contentType, alert.subject, alert.location), contentType)]); if (contentType === "help") onStatus("need_help"); };
  const openRelatedCamera=()=>{const query=new URLSearchParams({alert:alert.id,event:alert.eventId,at:alert.occurredAt});window.history.pushState({},"",`/camera/${encodeURIComponent(alert.cameraId)}?${query.toString()}`);window.dispatchEvent(new PopStateEvent("popstate"));};
  const handleAction = (action: QuickAction) => {
    if (action.id === "camera") {
      openRelatedCamera();
      return;
    }
    void respond(action.label, actionContentType(action.id));
  };
  const confirmSafe = () => { setSafeModal(false); onStatus("safe"); setMessages((items) => [...items, newMessage("assistant", "Cảm ơn bạn đã kiểm tra. Tôi đã đánh dấu sự kiện này là an toàn.", "success")]); };
  const falseAlarm = (_reason: string, _note: string) => { setFalseModal(false); onStatus("false_alarm"); setMessages((items) => [...items, newMessage("assistant", "Đã ghi nhận phản hồi của bạn. Sự kiện được đánh dấu là cảnh báo sai.", "text")]); };
  const helpAction = (label: string) => { if (label === "Mở camera") openRelatedCamera(); else window.alert(`${label}: Đây là thao tác mô phỏng, không thực hiện liên hệ thật.`); };
  const showQuickActions=alert.status==="pending"||alert.status==="checking";
  return <section className="alert-conversation"><AlertConversationHeader onBack={onBack} /><AlertSummaryBanner alert={alert} /><ChatMessageList messages={messages} alert={alert} typing={typing} onExpand={() => setSnapshotModal(true)} onCloseCamera={() => setMessages((items) => items.filter((message) => message.contentType !== "camera"))} onHelpAction={helpAction} onSafe={() => void respond("Tôi đã kiểm tra — An toàn", "success")} onFalseAlarm={() => void respond("Báo sai", "false_alarm")} contextualActions={showQuickActions?<div className="mobile-context-actions contextual-actions"><p>Thao tác khác</p><QuickActionList disabled={typing} status={alert.status} onAction={handleAction} exclude={["safe", "false_alarm"]} /></div>:undefined} />{safeModal && <ConfirmSafeModal subject={alert.subject} onCancel={() => setSafeModal(false)} onConfirm={confirmSafe} />}{falseModal && <FalseAlarmForm onCancel={() => setFalseModal(false)} onSubmit={falseAlarm} />}{snapshotModal && <SnapshotModal alert={alert} onClose={() => setSnapshotModal(false)} />}</section>;
}
