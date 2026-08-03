import { Activity, AlertTriangle, ArrowRight, Camera, Check, HeartHandshake, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import "./overview.css";
import { initialAlerts } from "../features/alerts/alertMockData";

const cameras = [
  { id:"camera-bedroom", area:"bedroom", name: "Phòng ngủ", lastSeen: "Phát hiện lúc 09:25", videoUrl:"/videos/45353-448489443_medium.mp4" },
  { id:"camera-living", area:"living", name: "Phòng khách", lastSeen: "Phát hiện lúc 09:18", videoUrl:"/videos/76621-559757958.mp4" },
  { id:"camera-front", area:"front", name: "Sân trước", lastSeen: "Hoạt động liên tục", videoUrl:"/videos/45353-448489443_medium.mp4" },
];
const cameraAreas=[{id:"all",label:"Tất cả"},{id:"bedroom",label:"Phòng ngủ"},{id:"living",label:"Phòng khách"},{id:"front",label:"Sân trước"}];

export default function OverviewPage() {
  const [cameraArea,setCameraArea]=useState("all");
  const navigate = (path: string) => { window.history.pushState({}, "", path); window.dispatchEvent(new PopStateEvent("popstate")); };
  const now=new Date(); const isToday=(value:string)=>{const date=new Date(value);return date.getFullYear()===now.getFullYear()&&date.getMonth()===now.getMonth()&&date.getDate()===now.getDate()};
  const todayAlerts=initialAlerts.filter(alert=>isToday(alert.occurredAt));
  const pendingTodayAlerts=todayAlerts.filter(alert=>alert.status==="pending"||alert.status==="checking"||alert.status==="need_help");
  const currentAlert=pendingTodayAlerts[0];
  const todayLabel=new Intl.DateTimeFormat("vi-VN",{weekday:"long",day:"2-digit",month:"long"}).format(now);
  const visibleCameras=cameraArea==="all"?cameras:cameras.filter(camera=>camera.area===cameraArea);

  return <div className="home-dashboard">
    <header className="home-welcome"><div><p>{todayLabel}</p><h1>Chào Minh, gia đình hôm nay</h1></div><span><ShieldCheck /> An Tâm đang bảo vệ</span></header>

    <section className="home-hero">
      <div className="hero-copy"><span className="hero-status-icon"><HeartHandshake /></span><p className="hero-eyebrow"><i /> Trạng thái hiện tại</p><h2>Ngôi nhà đang an toàn</h2><p>AI đang theo dõi 3 camera theo thời gian thực để phát hiện sớm những tình huống cần bạn chú ý.</p></div>
      <div className="hero-overview" aria-label="Tóm tắt hệ thống"><HeroMetric icon={Camera} value="3/3" label="Camera" /><HeroMetric icon={Activity} value={String(todayAlerts.length)} label="Sự kiện hôm nay" /></div>
      <div className="hero-orbit" aria-hidden="true"><span /><span /><ShieldCheck /></div>
    </section>

    <section className="home-section attention-section"><SectionHeading title="Cần bạn chú ý" description={currentAlert?`${pendingTodayAlerts.length} tình huống hôm nay đang chờ bạn kiểm tra.`:"Hôm nay không có tình huống nào đang chờ xử lý."} action="Xem tất cả" onAction={() => navigate("/alerts")} />
      {currentAlert?<article className="attention-card"><span className="attention-icon"><AlertTriangle /></span><div><p>Cảnh báo mới · {currentAlert.time}</p><h3>{currentAlert.title}</h3><span>{currentAlert.subject} · {currentAlert.location} · {currentAlert.preview}</span></div><button onClick={() => navigate(`/alerts/${encodeURIComponent(currentAlert.id)}`)}>Xem ngay <ArrowRight /></button></article>:<article className="attention-empty"><span><ShieldCheck/></span><div><strong>Không có cảnh báo mới hôm nay</strong><p>Hệ thống đang theo dõi theo thời gian thực.</p></div></article>}
    </section>

    <section className="home-section"><SectionHeading title="Camera" description="Không gian quan trọng quanh ngôi nhà." action="Mở camera" onAction={() => navigate("/camera")} />
      <div className="dashboard-camera-filters" role="group" aria-label="Lọc camera theo khu vực">{cameraAreas.map(area=><button key={area.id} className={cameraArea===area.id?"active":""} onClick={()=>setCameraArea(area.id)}>{area.label}</button>)}</div>
      <div className="home-camera-grid">{visibleCameras.map((camera) => <button className="home-camera-card" key={camera.name} onClick={() => navigate(`/camera/${camera.id}`)}><span className="home-camera-preview"><video src={camera.videoUrl} autoPlay loop muted playsInline preload="metadata"/><span className="camera-live"><i /> Trực tuyến</span><span className="dashboard-camera-name">{camera.name}</span></span><span className="camera-card-copy"><strong>{camera.name}</strong><small>{camera.lastSeen}</small></span><ArrowRight /></button>)}</div>
    </section>

    <section className="home-section insight-section"><article className="ai-insight-card"><span className="insight-icon"><Sparkles /></span><div><p>AI Insight · Hôm nay</p><h2>Mọi thứ đang diễn ra bình thường</h2><ul><li><Check /> Không phát hiện tình huống nguy hiểm mới</li><li><Check /> Ba camera đang hoạt động ổn định</li><li><Check /> Hai người thân đã được nhận diện tại nhà</li></ul></div></article></section>

  </div>;
}

function HeroMetric({ icon: Icon, value, label }: { icon: typeof Camera; value: string; label: string }) { return <div className="hero-metric"><Icon /><span><strong>{value}</strong><small>{label}</small></span></div>; }

function SectionHeading({ title, description, action, onAction }: { title: string; description: string; action?: string; onAction?: () => void }) { return <header className="home-section-heading"><div><h2>{title}</h2><p>{description}</p></div>{action && <button onClick={onAction}>{action}<ArrowRight /></button>}</header>; }
