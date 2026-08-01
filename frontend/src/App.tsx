import { useEffect, useState } from "react";
import { BarChart3, Bell, Camera, HeartHandshake, History, Home, Menu, Settings, ShieldCheck, UsersRound } from "lucide-react";
import AlertsPage from "./features/alerts/AlertsPage";
import CameraPage from "./pages/CameraPage";
import FamilyPage from "./pages/FamilyPage";
import HistoryPage from "./pages/HistoryPage";
import OverviewPage from "./pages/OverviewPage";
import SettingsPage from "./pages/SettingsPage";
import StatisticsPage from "./pages/StatisticsPage";
import FloatingAssistant from "./components/FloatingAssistant";
import CameraDetailPage from "./features/camera-detail/CameraDetailPage";

const navItems = [
  { label: "Tổng quan", path: "/", icon: Home, badge: undefined },
  { label: "Camera", path: "/camera", icon: Camera, badge: undefined },
  { label: "Cảnh báo", path: "/alerts", icon: Bell, badge: 1 },
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

function App() {
  const [activePath, setActivePath] = useState<RoutePath>(currentPath);
  const [routeRevision, setRouteRevision] = useState(0);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isMobileLayout, setIsMobileLayout] = useState(() => window.matchMedia("(max-width: 860px)").matches);

  useEffect(() => {
    const mobileQuery = window.matchMedia("(max-width: 860px)");
    const syncLayout = () => { setIsMobileLayout(mobileQuery.matches); setMobileOpen(false); };
    const syncRoute = () => { setActivePath(currentPath()); setRouteRevision((value) => value + 1); };
    syncLayout(); mobileQuery.addEventListener("change", syncLayout); window.addEventListener("resize", syncLayout); window.visualViewport?.addEventListener("resize", syncLayout); window.addEventListener("popstate", syncRoute);
    return () => { mobileQuery.removeEventListener("change", syncLayout); window.removeEventListener("resize", syncLayout); window.visualViewport?.removeEventListener("resize", syncLayout); window.removeEventListener("popstate", syncRoute); };
  }, []);

  const navigate = (path: RoutePath) => {
    if (path !== activePath) window.history.pushState({}, "", path);
    setActivePath(path);
    setMobileOpen(false);
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  };
  const activeNav = navItems.find((item) => item.path === activePath)?.label ?? "Tổng quan";

  return <div className={`app-shell ${isMobileLayout ? "mobile-layout" : "desktop-layout"} ${activePath === "/alerts" ? "alerts-active" : ""}`}>
    <aside className={`sidebar ${mobileOpen ? "is-open" : ""}`} aria-label="Điều hướng chính" aria-hidden={isMobileLayout && !mobileOpen}>
      <button className="brand brand-link" onClick={() => navigate("/")} aria-label="Về Tổng quan" title="An Tâm Home Care"><span className="brand-mark"><HeartHandshake /></span><span><strong>An Tâm</strong><small>Home Care</small></span></button>
      <nav>{navItems.map(({ label, path, icon: Icon, badge }) => <a key={path} href={path} title={label} className={`nav-item ${activePath === path ? "active" : ""}`} onClick={(event) => { event.preventDefault(); navigate(path); }} aria-current={activePath === path ? "page" : undefined}><Icon /><span>{label}</span>{badge ? <span className="nav-badge" aria-label={`${badge} cảnh báo chờ xử lý`}>{badge}</span> : null}</a>)}</nav>
      <div className="privacy-note"><ShieldCheck /><div><strong>Dữ liệu được bảo vệ</strong><span>Xử lý cục bộ, không gửi video thô lên cloud.</span></div></div>
    </aside>
    {isMobileLayout && mobileOpen && <button className="scrim" aria-label="Đóng menu" onClick={() => setMobileOpen(false)} />}
    <main className="main-content">
      <header className="topbar"><button className="icon-button menu-button" onClick={() => setMobileOpen(true)} aria-label="Mở menu"><Menu /></button><div className="topbar-spacer" /><div className="profile"><span className="avatar small">M</span><span><strong>Minh Nguyễn</strong><small>Người chăm sóc</small></span></div></header>
      <div className={`route-content ${activeNav === "Tổng quan" ? "overview-route" : ""}`} key={`${activePath}-${routeRevision}`}><RouteContent path={activePath} /></div>
    </main>
    {activePath !== "/alerts" && <FloatingAssistant />}
    {isMobileLayout && <nav className="mobile-bottom-nav" aria-label="Điều hướng nhanh trên điện thoại">{navItems.slice(0,4).map(({ label,path,icon:Icon,badge }) => <a key={path} href={path} className={activePath === path ? "active" : ""} onClick={(event) => { event.preventDefault(); navigate(path); }} aria-current={activePath === path ? "page" : undefined}><span className="mobile-nav-icon"><Icon />{badge ? <span className="mobile-nav-badge">{badge}</span> : null}</span><span>{label}</span></a>)}</nav>}
  </div>;
}

function RouteContent({ path }: { path: RoutePath }) {
  if (path === "/camera") return window.location.pathname.startsWith("/camera/") ? <CameraDetailPage cameraId={decodeURIComponent(window.location.pathname.split("/")[2] || "camera-bedroom")} /> : <CameraPage />;
  if (path === "/alerts") return <AlertsPage />;
  if (path === "/family") return <FamilyPage />;
  if (path === "/history") return <HistoryPage />;
  if (path === "/statistics") return <StatisticsPage />;
  if (path === "/settings") return <SettingsPage />;
  return <OverviewPage />;
}

export default App;
