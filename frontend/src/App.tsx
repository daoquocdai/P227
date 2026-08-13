import { useEffect, useState } from "react";
import { Bell, Camera, HeartHandshake, History, Home, LogOut, Menu, Settings, ShieldCheck, UsersRound } from "lucide-react";
import AlertsPage from "./features/alerts/AlertsPage";
import CameraPage from "./pages/CameraPage";
import FamilyPage from "./pages/FamilyPage";
import HistoryPage from "./pages/HistoryPage";
import OverviewPage from "./pages/OverviewPage";
import SettingsPage from "./pages/SettingsPage";
import { fetchAlerts } from "./features/alerts/alertService";
import { API_BASE_URL } from "./api/client";
import { logout, me, type AuthUser } from "./api/auth";
import LoginPage from "./pages/LoginPage";

const navItems = [
  { label: "Tổng quan", path: "/", icon: Home, badge: undefined },
  { label: "Camera", path: "/camera", icon: Camera, badge: undefined },
  { label: "Cảnh báo", path: "/alerts", icon: Bell, badge: undefined },
  { label: "Người thân", path: "/family", icon: UsersRound, badge: undefined },
  { label: "Lịch sử", path: "/history", icon: History, badge: undefined },
  { label: "Cài đặt", path: "/settings", icon: Settings, badge: undefined },
] as const;

type RoutePath = typeof navItems[number]["path"];
const routePaths = new Set<string>(navItems.map((item) => item.path));
const currentPath = (): RoutePath => {
  if (window.location.pathname.startsWith("/alerts/")) return "/alerts";
  if (window.location.pathname.startsWith("/camera/")) return "/camera";
  return routePaths.has(window.location.pathname) ? window.location.pathname as RoutePath : "/";
};

function DashboardApp({user,onLogout}:{user:AuthUser;onLogout:()=>void}) {
  const [activePath, setActivePath] = useState<RoutePath>(currentPath);
  const [routeRevision, setRouteRevision] = useState(0);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [unreadAlerts, setUnreadAlerts] = useState(0);
  const [accessNotice,setAccessNotice]=useState("");
  const [confirmLogout,setConfirmLogout]=useState(false);
  const [isMobileLayout, setIsMobileLayout] = useState(() => window.matchMedia("(max-width: 860px)").matches);

  useEffect(() => {
    const mobileQuery = window.matchMedia("(max-width: 860px)");
    const syncLayout = () => { setIsMobileLayout(mobileQuery.matches); setMobileOpen(false); };
    const syncRoute = () => { setActivePath(currentPath()); setRouteRevision((value) => value + 1); };
    syncLayout(); mobileQuery.addEventListener("change", syncLayout); window.addEventListener("resize", syncLayout); window.visualViewport?.addEventListener("resize", syncLayout); window.addEventListener("popstate", syncRoute);
    return () => { mobileQuery.removeEventListener("change", syncLayout); window.removeEventListener("resize", syncLayout); window.visualViewport?.removeEventListener("resize", syncLayout); window.removeEventListener("popstate", syncRoute); };
  }, []);
  useEffect(()=>{if(!confirmLogout)return;const close=(event:KeyboardEvent)=>{if(event.key==="Escape")setConfirmLogout(false)};window.addEventListener("keydown",close);return()=>window.removeEventListener("keydown",close)},[confirmLogout]);
  useEffect(() => {
    const stream = new EventSource(`${API_BASE_URL}/alerts/stream`);
    const sync = () => window.dispatchEvent(new CustomEvent("antam:alerts-changed"));
    stream.addEventListener("ready", sync);
    stream.addEventListener("alert", sync);
    return () => { stream.removeEventListener("ready", sync); stream.removeEventListener("alert", sync); stream.close(); };
  }, []);
  useEffect(() => {
    const refreshUnread = () => { void fetchAlerts().then((items) => setUnreadAlerts(items.filter((item) => item.unread).length)).catch(() => undefined); };
    refreshUnread();
    const timer = window.setInterval(refreshUnread, 15_000);
    window.addEventListener("focus", refreshUnread);
    window.addEventListener("antam:alerts-changed", refreshUnread);
    window.addEventListener("antam:alert-status", refreshUnread);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", refreshUnread); window.removeEventListener("antam:alerts-changed", refreshUnread); window.removeEventListener("antam:alert-status", refreshUnread); };
  }, []);

  const navigate = (path: RoutePath) => {
    if (path !== activePath) window.history.pushState({}, "", path);
    setActivePath(path);
    setMobileOpen(false);
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  };
  const canManageSettings=user.role==="admin"||user.permissions.manage_cameras||user.permissions.manage_persons||user.permissions.manage_users;
  const canOpen=(path:RoutePath)=>(path!=="/history"||user.role==="admin"||user.permissions.view_history)&&(path!=="/settings"||canManageSettings);
  useEffect(()=>{if(!canOpen(activePath)){setAccessNotice("Bạn không có quyền truy cập mục này. Liên hệ quản trị viên để được cấp quyền.");window.history.replaceState({},"","/");setActivePath("/")}},[activePath,user]);
  const activeNav = navItems.find((item) => item.path === activePath)?.label ?? "Tổng quan";

  return <div className={`app-shell ${isMobileLayout ? "mobile-layout" : "desktop-layout"} ${activePath === "/alerts" ? "alerts-active" : ""} ${canOpen("/history")?"":"no-history"} ${canManageSettings?"":"no-settings"} ${user.role==="admin"||user.permissions.resolve_alert?"":"no-resolve-alert"} role-${user.role}`}>
    <aside className={`sidebar ${mobileOpen ? "is-open" : ""}`} aria-label="Điều hướng chính" aria-hidden={isMobileLayout && !mobileOpen}>
      <button className="brand brand-link" onClick={() => navigate("/")} aria-label="Về Tổng quan" title="GuardianCam Local Hub"><span className="brand-mark"><HeartHandshake /></span><span><strong>GuardianCam</strong><small>Local Hub</small></span></button>
      <nav>{navItems.map(({ label, path, icon: Icon }) => { const badge = path === "/alerts" ? unreadAlerts : 0; return <a key={path} href={path} title={label} className={`nav-item ${activePath === path ? "active" : ""}`} onClick={(event) => { event.preventDefault(); navigate(path); }} aria-current={activePath === path ? "page" : undefined}><Icon /><span>{label}</span>{badge > 0 ? <span className="nav-badge" aria-label={`${badge} cảnh báo chưa đọc`}>{badge > 99 ? "99+" : badge}</span> : null}</a>; })}</nav>
      <div className="privacy-note"><ShieldCheck /><div><strong>Dữ liệu được bảo vệ</strong><span>Xử lý cục bộ, không gửi video thô lên cloud.</span></div></div>
    </aside>
    {isMobileLayout && mobileOpen && <button className="scrim" aria-label="Đóng menu" onClick={() => setMobileOpen(false)} />}
    <main className="main-content">
      <header className="topbar"><button className="icon-button menu-button" onClick={() => setMobileOpen(true)} aria-label="Mở menu"><Menu /></button><div className="topbar-spacer" />{activePath === "/alerts" && <span className="topbar-protection"><ShieldCheck /> Đang bảo vệ</span>}<div className="profile"><span className="avatar small">{user.name[0]}</span><span><strong>{user.name}</strong><small>{user.role==="admin"?"Quản trị viên":"Người chăm sóc"}</small></span></div><button className="logout-button" onClick={()=>setConfirmLogout(true)} title="Đăng xuất" aria-label="Đăng xuất"><LogOut/><span>Đăng xuất</span></button></header>
      <div className={`route-content ${activeNav === "Tổng quan" ? "overview-route" : ""} ${activePath === "/history" ? "history-route" : ""} ${activePath === "/family" ? "family-route" : ""}`} key={`${activePath}-${routeRevision}`}>{accessNotice&&<button className="access-notice" onClick={()=>setAccessNotice("")}>{accessNotice}</button>}<RouteContent path={activePath} /></div>
    </main>
    {isMobileLayout && <nav className="mobile-bottom-nav" aria-label="Điều hướng nhanh trên điện thoại">{navItems.slice(0,4).map(({ label,path,icon:Icon }) => { const badge = path === "/alerts" ? unreadAlerts : 0; return <a key={path} href={path} className={activePath === path ? "active" : ""} onClick={(event) => { event.preventDefault(); navigate(path); }} aria-current={activePath === path ? "page" : undefined}><span className="mobile-nav-icon"><Icon />{badge > 0 ? <span className="mobile-nav-badge">{badge > 99 ? "99+" : badge}</span> : null}</span><span>{label}</span></a>; })}</nav>}
    {confirmLogout&&<div className="logout-dialog-backdrop" onMouseDown={(event)=>{if(event.target===event.currentTarget)setConfirmLogout(false)}}><section className="logout-dialog" role="dialog" aria-modal="true" aria-labelledby="logout-title"><span className="logout-dialog-icon"><LogOut/></span><h2 id="logout-title">Bạn muốn đăng xuất?</h2><p>Bạn sẽ cần đăng nhập lại để tiếp tục sử dụng hệ thống An Tâm.</p><div><button autoFocus onClick={()=>setConfirmLogout(false)}>Ở lại</button><button className="confirm-logout" onClick={onLogout}>Đăng xuất</button></div></section></div>}
  </div>;
}

function RouteContent({ path }: { path: RoutePath }) {
  if (path === "/camera") return <CameraPage />;
  if (path === "/alerts") return <AlertsPage />;
  if (path === "/family") return <FamilyPage />;
  if (path === "/history") return <HistoryPage />;
  if (path === "/settings") return <SettingsPage />;
  return <OverviewPage />;
}

function App(){
 const [user,setUser]=useState<AuthUser|null>(null);const [checking,setChecking]=useState(true);
 useEffect(()=>{me().then(setUser).catch(()=>setUser(null)).finally(()=>setChecking(false))},[]);
 if(checking)return <div className="auth-loading" aria-label="Đang tải"/>;
 if(!user||user.force_password_change)return <LoginPage user={user} onAuthenticated={setUser}/>;
 return <DashboardApp user={user} onLogout={()=>void logout().finally(()=>setUser(null))}/>;
}

export default App;
