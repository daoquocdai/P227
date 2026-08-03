import { Camera, CircleCheck, CircleHelp, Image, LifeBuoy, ThumbsDown } from "lucide-react";
import { quickActions } from "./alertMockData";
import type { QuickAction } from "./alert.types";
import type { AlertStatus } from "./alert.types";
const icons = { camera: Camera, snapshot: Image, safe: CircleCheck, help: LifeBuoy, why: CircleHelp, false_alarm: ThumbsDown };
const mobileLabels: Partial<Record<QuickAction["id"], string>> = { safe: "Xác nhận người thân an toàn", help: "Cần hỗ trợ", why: "Tại sao có cảnh báo?" };
export function QuickActionList({ disabled, status, onAction }: { disabled: boolean; status?: AlertStatus; onAction: (action: QuickAction) => void }) { const terminal = status === "safe" || status === "false_alarm" || status === "resolved"; return <div className="quick-action-list">{quickActions.map((action) => { const Icon = icons[action.id]; const actionDisabled = disabled || (terminal && ["safe", "help", "false_alarm"].includes(action.id)); return <button key={action.id} disabled={actionDisabled} className={`quick-${action.id}`} onClick={() => onAction(action)}><Icon /><span className="quick-label-desktop">{action.label}</span><span className="quick-label-mobile">{mobileLabels[action.id] ?? action.label}</span></button>; })}</div>; }
