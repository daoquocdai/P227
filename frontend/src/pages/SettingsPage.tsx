import { useMemo, useState } from "react";
import {
  ArrowLeft, Bell, Camera, Check, ChevronRight, History, LockKeyhole,
  Settings, ShieldCheck, UserCog, UsersRound,
} from "lucide-react";
import "./settings.css";
import { GeneralSettings, NotificationSettings, UsersSettings } from "./SettingsSections";

type PermissionKey = "view_history" | "acknowledge_alert" | "resolve_alert" | "manage_cameras" | "manage_persons" | "manage_users";
type Caregiver = { id: string; displayName: string; email: string; isActive: boolean; initials: string };
type PermissionState = Record<PermissionKey, boolean>;

const caregivers: Caregiver[] = [
  { id: "caregiver-minh", displayName: "Minh Nguyễn", email: "caregiver@example.local", isActive: true, initials: "MN" },
  { id: "caregiver-mai", displayName: "Mai Anh", email: "maianh@example.local", isActive: true, initials: "MA" },
  { id: "caregiver-ha", displayName: "Thanh Hà", email: "thanhha@example.local", isActive: false, initials: "TH" },
];

const defaults = (): PermissionState => ({
  view_history: true, acknowledge_alert: true, resolve_alert: false,
  manage_cameras: false, manage_persons: false, manage_users: false,
});

const permissionGroups: { title: string; icon: typeof History; items: { key: PermissionKey; label: string; description: string }[] }[] = [
  { title: "Xem & xử lý cảnh báo", icon: Bell, items: [
    { key: "view_history", label: "Xem Lịch sử", description: "Tra cứu sự kiện và lịch sử xử lý đã ghi nhận." },
    { key: "acknowledge_alert", label: "Xác nhận cảnh báo", description: "Xác nhận đã tiếp nhận và kiểm tra cảnh báo." },
    { key: "resolve_alert", label: "Xử lý / đóng cảnh báo", description: "Đánh dấu tình huống đã được xử lý hoàn tất." },
  ] },
  { title: "Quản trị hệ thống", icon: Settings, items: [
    { key: "manage_cameras", label: "Quản lý camera", description: "Thêm, chỉnh sửa và thay đổi trạng thái camera." },
    { key: "manage_persons", label: "Quản lý thành viên & khuôn mặt", description: "Quản lý người thân và hồ sơ nhận diện." },
    { key: "manage_users", label: "Quản lý tài khoản người dùng", description: "Thêm, khóa và cập nhật tài khoản hệ thống." },
  ] },
];

const tabs = [
  { id: "general", label: "Cài đặt chung", icon: Settings },
  { id: "users", label: "Quản lý người dùng", icon: UsersRound },
  { id: "permissions", label: "Phân quyền", icon: LockKeyhole },
  { id: "notifications", label: "Thông báo", icon: Bell },
] as const;

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]["id"]>("general");
  const [permissionIsNew, setPermissionIsNew] = useState(true);
  const [selectedId, setSelectedId] = useState(caregivers[0]?.id ?? "");
  const [mobileDetail, setMobileDetail] = useState(false);
  const [savedKey, setSavedKey] = useState<PermissionKey | null>(null);
  const [permissions, setPermissions] = useState<Record<string, PermissionState>>(() => ({
    "caregiver-minh": defaults(),
    "caregiver-mai": { ...defaults(), resolve_alert: true, manage_persons: true },
    "caregiver-ha": defaults(),
  }));
  const selected = useMemo(() => caregivers.find((item) => item.id === selectedId), [selectedId]);

  const togglePermission = (key: PermissionKey) => {
    if (!selected?.isActive) return;
    setPermissions((current) => ({ ...current, [selected.id]: { ...current[selected.id], [key]: !current[selected.id][key] } }));
    setSavedKey(key);
    window.setTimeout(() => setSavedKey((current) => current === key ? null : current), 1400);
  };

  return <section className="settings-page page-wrap">
    <header className="settings-heading"><div><h1>Cài đặt</h1><p>Quản lý hệ thống, tài khoản và quyền truy cập.</p></div><span><ShieldCheck /> Chỉ dành cho quản trị viên</span></header>
    <div className="settings-shell">
      <nav className="settings-tabs" aria-label="Danh mục cài đặt">{tabs.map(({ id, label, icon: Icon }) => <button key={id} className={activeTab === id ? "active" : ""} onClick={() => { setActiveTab(id); if (id === "permissions") setPermissionIsNew(false); }}><Icon /><span>{label}</span>{id === "permissions" && permissionIsNew && <small>Mới</small>}<ChevronRight /></button>)}</nav>
      <main className="settings-content">
        {activeTab === "general" ? <GeneralSettings /> : activeTab === "users" ? <UsersSettings /> : activeTab === "notifications" ? <NotificationSettings /> : <div className={`permission-view ${mobileDetail ? "show-detail" : ""}`}>
          <header className="permission-heading"><div><h2>Phân quyền thành viên</h2><p>Quản lý quyền truy cập và thao tác của từng thành viên trong hệ thống.</p></div><span>{caregivers.length} caregiver</span></header>
          {caregivers.length === 0 ? <div className="permission-empty"><UserCog /><h3>Chưa có thành viên nào khác</h3><p>Thêm thành viên ở mục Quản lý người dùng để phân quyền.</p><button onClick={() => setActiveTab("users")}>Đi tới Quản lý người dùng</button></div> : <div className="permission-layout">
            <aside className="caregiver-panel"><div className="caregiver-panel-title"><strong>Thành viên</strong><small>Chọn caregiver để chỉnh quyền</small></div><div className="caregiver-list">{caregivers.map((caregiver) => <button key={caregiver.id} className={selectedId === caregiver.id ? "selected" : ""} onClick={() => { setSelectedId(caregiver.id); setMobileDetail(true); }}><span className="caregiver-avatar">{caregiver.initials}</span><span><strong>{caregiver.displayName}</strong><small>{caregiver.email}</small></span><i className={caregiver.isActive ? "active" : "inactive"}>{caregiver.isActive ? "Hoạt động" : "Đã khóa"}</i><ChevronRight /></button>)}</div></aside>
            {selected && <section className="permission-panel"><header><button className="permission-back" onClick={() => setMobileDetail(false)} aria-label="Quay lại danh sách"><ArrowLeft /></button><span className="caregiver-avatar large">{selected.initials}</span><div><h3>{selected.displayName}</h3><p>{selected.email}</p></div><i className={selected.isActive ? "active" : "inactive"}>{selected.isActive ? "Đang hoạt động" : "Tài khoản đã khóa"}</i></header>{!selected.isActive && <div className="inactive-notice"><LockKeyhole /><span>Tài khoản đang bị khóa. Kích hoạt lại tài khoản để thay đổi quyền.</span></div>}<div className="permission-groups">{permissionGroups.map(({ title, icon: GroupIcon, items }) => <section key={title}><h4><GroupIcon /> {title}</h4>{items.map((item) => <div className={`permission-row ${!selected.isActive ? "disabled" : ""}`} key={item.key}><div><strong>{item.label}</strong><p>{item.description}</p></div><div className="permission-control">{savedKey === item.key && <span className="saved-feedback"><Check /> Đã lưu</span>}<button role="switch" aria-checked={permissions[selected.id][item.key]} aria-label={item.label} disabled={!selected.isActive} className={`permission-toggle ${permissions[selected.id][item.key] ? "on" : ""}`} onClick={() => togglePermission(item.key)}><i /></button></div></div>)}</section>)}</div><footer><ShieldCheck /><span>Admin luôn có toàn quyền. Các thay đổi của caregiver được lưu ngay khi bật hoặc tắt.</span></footer></section>}
          </div>}
        </div>}
      </main>
    </div>
  </section>;
}
