import { Activity, AlertTriangle, ArrowRight, Camera, Check, HeartHandshake, RefreshCw, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { getOverview, type OverviewData } from "../api/overview";
import "./overview.css";
import "./overviewApi.css";

export default function OverviewPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [cameraArea, setCameraArea] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = () => {
    setLoading(true);
    setError(false);
    getOverview().then(setData).catch(() => setError(true)).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const navigate = (path: string) => {
    window.history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  };
  const todayLabel = new Intl.DateTimeFormat("vi-VN", { weekday: "long", day: "2-digit", month: "long" }).format(new Date());
  const areas = useMemo(() => [
    { id: "all", label: "Tất cả" },
    ...(data?.cameras.map((camera) => ({ id: camera.id, label: camera.location })) ?? []),
  ], [data]);
  const visibleCameras = data?.cameras.filter((camera) => cameraArea === "all" || camera.id === cameraArea) ?? [];

  if (loading && !data) return <div className="overview-loading"><ShieldCheck /><strong>Đang tải dữ liệu Local Hub…</strong></div>;
  if (error && !data) return <div className="overview-error"><AlertTriangle /><strong>Không kết nối được backend</strong><p>Hãy kiểm tra FastAPI đang chạy tại cổng 8000.</p><button onClick={load}><RefreshCw /> Thử lại</button></div>;
  if (!data) return null;

  const alert = data.currentAlert;
  const statusAttention = data.systemStatus === "attention";
  return <div className="home-dashboard">
    <header className="home-welcome"><div><p>{todayLabel}</p><h1>Tổng quan chăm sóc gia đình</h1></div><span><ShieldCheck /> Local Hub đang bảo vệ</span></header>

    <section className={`home-hero ${statusAttention ? "attention" : ""}`}>
      <div className="hero-copy"><span className="hero-status-icon">{statusAttention ? <AlertTriangle /> : <HeartHandshake />}</span><p className="hero-eyebrow"><i /> Trạng thái hiện tại</p><h2>{data.headline}</h2><p>{data.summary}</p></div>
      <div className="hero-overview" aria-label="Tóm tắt hệ thống"><HeroMetric icon={Camera} value={`${data.metrics.onlineCameras}/${data.metrics.totalCameras}`} label="Camera" /><HeroMetric icon={Activity} value={String(data.metrics.eventsToday)} label="Sự kiện hôm nay" /></div>
      <div className="hero-orbit" aria-hidden="true"><span /><span /><ShieldCheck /></div>
    </section>

    <section className="home-section attention-section"><SectionHeading title="Cần bạn chú ý" description={alert ? `${data.metrics.pendingAlerts} tình huống hôm nay đang chờ bạn kiểm tra.` : "Hôm nay không có tình huống nào đang chờ xử lý."} action="Xem tất cả" onAction={() => navigate("/alerts")} />
      {alert ? <article className="attention-card"><span className="attention-icon"><AlertTriangle /></span><div><p>Cảnh báo mới · {formatTime(alert.occurredAt)}</p><h3>{alert.title}</h3><span>{alert.subject} · {alert.location} · {alert.preview}</span></div><button onClick={() => navigate(`/alerts/${encodeURIComponent(alert.id)}`)}>Xem ngay <ArrowRight /></button></article> : <article className="attention-empty"><span><ShieldCheck /></span><div><strong>Không có cảnh báo mới hôm nay</strong><p>Hệ thống đang theo dõi theo thời gian thực.</p></div></article>}
    </section>

    <section className="home-section"><SectionHeading title="Camera" description="Dữ liệu camera được quản lý bởi Local Hub." action="Mở camera" onAction={() => navigate("/camera")} />
      <div className="dashboard-camera-filters" role="group" aria-label="Lọc camera theo khu vực">{areas.map((area) => <button key={area.id} className={cameraArea === area.id ? "active" : ""} onClick={() => setCameraArea(area.id)}>{area.label}</button>)}</div>
      <div className="home-camera-grid">{visibleCameras.map((camera) => <button className="home-camera-card" key={camera.id} onClick={() => navigate(`/camera?camera=${encodeURIComponent(camera.id)}`)}><span className="home-camera-preview"><CameraPreview camera={camera} /><span className={`camera-live ${camera.status}`}><i /> {camera.status === "online" ? "Ảnh gần nhất" : "Ngoại tuyến"}</span><span className="dashboard-camera-name">{camera.name}</span></span><span className="camera-card-copy"><strong>{camera.location || "Chưa đặt vị trí"}</strong><small>{camera.lastSeenAt ? `Cập nhật ${formatTime(camera.lastSeenAt)}` : "Chưa có dữ liệu gần đây"}</small>{camera.visionEnabled && <small>Vision: {camera.visionStatus ?? "đang chờ"}</small>}</span><ArrowRight /></button>)}</div>
    </section>

    <section className="home-section insight-section"><article className="ai-insight-card"><span className="insight-icon"><Sparkles /></span><div><p>TÓM TẮT HỆ THỐNG · HÔM NAY</p><h2>{statusAttention ? "Có dữ liệu cần được kiểm tra" : "Mọi thứ đang diễn ra bình thường"}</h2><ul>{data.insights.map((insight) => <li key={insight}><Check /> {insight}</li>)}</ul></div></article></section>
  </div>;
}

function CameraPreview({ camera }: { camera: OverviewData["cameras"][number] }) {
  const [failed, setFailed] = useState(false);
  if (!camera.previewUrl || failed) return <span className="overview-camera-placeholder"><Camera /></span>;
  const separator = camera.previewUrl.includes("?") ? "&" : "?";
  return <img src={`${camera.previewUrl}${separator}v=${camera.previewVersion ?? 0}`} alt={`Ảnh gần nhất ${camera.name}`} onError={() => setFailed(true)} />;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit" }).format(date);
}

function HeroMetric({ icon: Icon, value, label }: { icon: typeof Camera; value: string; label: string }) {
  return <div className="hero-metric"><Icon /><span><strong>{value}</strong><small>{label}</small></span></div>;
}

function SectionHeading({ title, description, action, onAction }: { title: string; description: string; action?: string; onAction?: () => void }) {
  return <header className="home-section-heading"><div><h2>{title}</h2><p>{description}</p></div>{action && <button onClick={onAction}>{action}<ArrowRight /></button>}</header>;
}
