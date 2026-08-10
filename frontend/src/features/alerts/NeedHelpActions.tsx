import { Camera, CheckCircle2, NotebookPen, Phone, UserRound } from "lucide-react";
const actions = [{ label: "Gọi người thân", icon: Phone }, { label: "Liên hệ người chăm sóc", icon: UserRound }, { label: "Mở camera", icon: Camera }, { label: "Thêm ghi chú", icon: NotebookPen }, { label: "Đánh dấu đã xử lý", icon: CheckCircle2 }];
export function NeedHelpActions({ onAction }: { onAction: (label: string) => void }) { return <div className="need-help-grid">{actions.map(({ label, icon: Icon }) => <button key={label} onClick={() => onAction(label)}><Icon /><span>{label}</span></button>)}</div>; }

