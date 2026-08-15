import { Camera, Check, ThumbsDown } from "lucide-react";
import { useState } from "react";
import type { AlertEvent } from "./alert.types";
import { AlertConversationHeader } from "./AlertConversationHeader";
import { AlertSummaryBanner } from "./AlertSummaryBanner";
import { ConfirmSafeModal } from "./ConfirmSafeModal";
import { FalseAlarmForm } from "./FalseAlarmForm";
import { SnapshotCard } from "./SnapshotCard";
import { SnapshotModal } from "./SnapshotModal";

export function AlertConversation({ alert, onBack, onStatus }: { alert: AlertEvent; onBack: () => void; onStatus: (status: AlertEvent["status"], note?: string) => void }) {
  const [safeModal, setSafeModal] = useState(false);
  const [falseModal, setFalseModal] = useState(false);
  const [snapshotModal, setSnapshotModal] = useState(false);
  const terminal = ["safe", "false_alarm", "resolved"].includes(alert.status);
  const openCamera = () => {
    window.history.pushState({}, "", `/camera?camera=${encodeURIComponent(alert.cameraId)}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  };
  return <section className="alert-conversation">
    <AlertConversationHeader onBack={onBack} />
    <AlertSummaryBanner alert={alert} />
    <div className="alert-product-detail">
      <SnapshotCard alert={alert} onExpand={() => alert.snapshotUrl && setSnapshotModal(true)} />
      <section className="alert-product-copy"><h2>{alert.title}</h2><p>{alert.preview}</p><dl><div><dt>Người liên quan</dt><dd>{alert.subject}</dd></div><div><dt>Vị trí</dt><dd>{alert.location}</dd></div><div><dt>{alert.type === "stranger" ? "Mức độ không khớp" : "Độ tin cậy"}</dt><dd>{alert.confidence ?? 0}%</dd></div></dl></section>
      <div className="alert-product-actions"><button onClick={openCamera}><Camera /> Mở camera</button><button disabled={terminal} onClick={() => setSafeModal(true)}><Check /> Xác nhận an toàn</button><button disabled={terminal} onClick={() => setFalseModal(true)}><ThumbsDown /> Báo sai</button></div>
    </div>
    {safeModal && <ConfirmSafeModal subject={alert.subject} onCancel={() => setSafeModal(false)} onConfirm={() => { setSafeModal(false); onStatus("safe", "Người dùng xác nhận an toàn"); }} />}
    {falseModal && <FalseAlarmForm onCancel={() => setFalseModal(false)} onSubmit={(reason, note) => { setFalseModal(false); onStatus("false_alarm", [reason, note].filter(Boolean).join(": ")); }} />}
    {snapshotModal && alert.snapshotUrl && <SnapshotModal alert={alert} onClose={() => setSnapshotModal(false)} />}
  </section>;
}
