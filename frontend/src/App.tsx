import { useEffect, useState } from "react";
import { BarChart3, Bell, Camera, HeartHandshake, History, Home, LogOut, Menu, Settings, ShieldCheck, UsersRound } from "lucide-react";
import AlertsPage from "./features/alerts/AlertsPage";
import CameraPage from "./pages/CameraPage";
import FamilyPage from "./pages/FamilyPage";
import HistoryPage from "./pages/HistoryPage";
import OverviewPage from "./pages/OverviewPage";
import SettingsPage from "./pages/SettingsPage";
import StatisticsPage from "./pages/StatisticsPage";
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
  { label: "Thống kê", path: "/statistics", icon: BarChart3, badge: undefined },
  { label: "Cài đặt", path: "/settings", icon: Settings, badge: undefined },
] as const;

type RoutePath = typeof navItems[number]["path"];
const routePaths = new Set<string>(navItems.map((item) => item.path));
const currentPath = (): RoutePath => {
  if (window.location.pathname.startsWith("/alerts/")) return "/alerts";
  if (window.location.pathname.startsWith("/camera/")) return "/camera";
  return routePaths.has(window.location.pathname) ? window.location.pathname as RoutePath : "/";
};

function DashboardApp({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const [activePath, setActivePath] = useState<RoutePath>(currentPath);
  const [routeRevision, setRouteRevision] = useState(0);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [unreadAlerts, setUnreadAlerts] = useState(0);
  const [isMobileLayout, setIsMobileLayout] = useState(() => window.matchMedia("(max-width: 860px)").matches);

  useEffect(() => {
    const mobileQuery = window.matchMedia("(max-width: 860px)");
    const syncLayout = () => { setIsMobileLayout(mobileQuery.matches); setMobileOpen(false); };
    const syncRoute = () => { setActivePath(currentPath()); setRouteRevision((value) => value + 1); };
    syncLayout(); mobileQuery.addEventListener("change", syncLayout); window.addEventListener("resize", syncLayout); window.visualViewport?.addEventListener("resize", syncLayout); window.addEventListener("popstate", syncRoute);
    return () => { mobileQuery.removeEventListener("change", syncLayout); window.removeEventListener("resize", syncLayout); window.visualViewport?.removeEventListener("resize", syncLayout); window.removeEventListener("popstate", syncRoute); };
  }, []);
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
  const activeNav = navItems.find((item) => item.path === activePath)?.label ?? "Tổng quan";
  const visibleNav = navItems.filter(item => item.path !== "/statistics" || user.role === "admin");
  useEffect(() => {
    if (activePath === "/statistics" && user.role !== "admin") {
      window.history.replaceState({}, "", "/");
      setActivePath("/");
    }
  }, [activePath, user.role]);

  return <div className={`app-shell ${isMobileLayout ? "mobile-layout" : "desktop-layout"} ${activePath === "/alerts" ? "alerts-active" : ""}`}>
    <aside className={`sidebar ${mobileOpen ? "is-open" : ""}`} aria-label="Điều hướng chính" aria-hidden={isMobileLayout && !mobileOpen}>
      <button className="brand brand-link" onClick={() => navigate("/")} aria-label="Về Tổng quan" title="GuardianCam Local Hub"><span className="brand-mark"><HeartHandshake /></span><span><strong>GuardianCam</strong><small>Local Hub</small></span></button>
      <nav>{visibleNav.map(({ label, path, icon: Icon }) => { const badge = path === "/alerts" ? unreadAlerts : 0; return <a key={path} href={path} title={label} className={`nav-item ${activePath === path ? "active" : ""}`} onClick={(event) => { event.preventDefault(); navigate(path); }} aria-current={activePath === path ? "page" : undefined}><Icon /><span>{label}</span>{badge > 0 ? <span className="nav-badge" aria-label={`${badge} cảnh báo chưa đọc`}>{badge > 99 ? "99+" : badge}</span> : null}</a>; })}</nav>
      <div className="privacy-note"><ShieldCheck /><div><strong>Dữ liệu được bảo vệ</strong><span>Xử lý cục bộ, không gửi video thô lên cloud.</span></div></div>
    </aside>
    {isMobileLayout && mobileOpen && <button className="scrim" aria-label="Đóng menu" onClick={() => setMobileOpen(false)} />}
    <main className="main-content">
      <header className="topbar"><button className="icon-button menu-button" onClick={() => setMobileOpen(true)} aria-label="Mở menu"><Menu /></button><div className="topbar-spacer" />{activePath === "/alerts" && <span className="topbar-protection"><ShieldCheck /> Đang bảo vệ</span>}<div className="profile"><span className="avatar small">{user.name[0]}</span><span><strong>{user.name}</strong><small>{user.role === "admin" ? "Quản trị viên" : "Người chăm sóc"}</small></span></div><button className="logout-button" onClick={onLogout} title="Đăng xuất"><LogOut /><span>Đăng xuất</span></button></header>
      <div className={`route-content ${activeNav === "Tổng quan" ? "overview-route" : ""} ${activePath === "/history" ? "history-route" : ""} ${activePath === "/family" ? "family-route" : ""}`} key={`${activePath}-${routeRevision}`}><RouteContent path={activePath} /></div>
    </main>
    {isMobileLayout && <nav className="mobile-bottom-nav" aria-label="Điều hướng nhanh trên điện thoại">{navItems.slice(0,4).map(({ label,path,icon:Icon }) => { const badge = path === "/alerts" ? unreadAlerts : 0; return <a key={path} href={path} className={activePath === path ? "active" : ""} onClick={(event) => { event.preventDefault(); navigate(path); }} aria-current={activePath === path ? "page" : undefined}><span className="mobile-nav-icon"><Icon />{badge > 0 ? <span className="mobile-nav-badge">{badge > 99 ? "99+" : badge}</span> : null}</span><span>{label}</span></a>; })}</nav>}
  </div>;
}

function RouteContent({ path }: { path: RoutePath }) {
  if (path === "/camera") return <CameraPage />;
  if (path === "/alerts") return <AlertsPage />;
  if (path === "/family") return <FamilyPage />;
  if (path === "/history") return <HistoryPage />;
  if (path === "/statistics") return <StatisticsPage />;
  if (path === "/settings") return <SettingsPage />;
  return <OverviewPage />;
}

function App() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checking, setChecking] = useState(true);
  useEffect(() => { me().then(setUser).catch(() => setUser(null)).finally(() => setChecking(false)); }, []);
  if (checking) return <div className="auth-loading" aria-label="Đang tải">Đang tải…</div>;
  if (!user || user.force_password_change) return <LoginPage user={user} onAuthenticated={setUser} />;
  return <DashboardApp user={user} onLogout={() => void logout().finally(() => setUser(null))} />;
}

export default App;
