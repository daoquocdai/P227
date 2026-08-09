import { AlertTriangle, Camera, CameraOff, ChevronLeft, ChevronRight, Info, RefreshCw, ShieldCheck, Video, Wifi } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { getCamera, getCameras, type CameraDto, type CameraEventDto } from "../api/cameras";
import { CameraStream } from "../components";
import "./cameraViewer.css";
import "./cameraApi.css";

export default function CameraPage() {
  const [feeds, setFeeds] = useState<CameraDto[]>([]);
  const [selectedId, setSelectedId] = useState(() => new URLSearchParams(window.location.search).get("camera") ?? "");
  const [events, setEvents] = useState<CameraEventDto[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const selectorRef = useRef<HTMLDivElement>(null);

  const load = () => {
    setLoading(true); setError(false);
    getCameras().then((items) => { setFeeds(items); setSelectedId((current) => items.some((item) => item.id === current) ? current : items[0]?.id || ""); })
      .catch(() => setError(true)).finally(() => setLoading(false));
  };
  useEffect(load, []);
  useEffect(() => {
    if (!selectedId) return;
    getCamera(selectedId).then((camera) => setEvents(camera.events ?? [])).catch(() => setEvents([]));
  }, [selectedId]);

  const selected = feeds.find((feed) => feed.id === selectedId);
  const todayEvents = events.filter((event) => isToday(event.occurred_at));
  const offline = !selected || selected.status !== "online";
  const navigate = (path: string) => { window.history.pushState({}, "", path); window.dispatchEvent(new PopStateEvent("popstate")); };
  const moveCarousel = (direction: -1 | 1) => selectorRef.current?.scrollBy({ left: direction * 220, behavior: "smooth" });

  if (loading) return <div className="camera-api-state"><ShieldCheck /><strong>Đang tải camera từ Local Hub…</strong></div>;
  if (error) return <div className="camera-api-state error"><CameraOff /><strong>Không kết nối được backend</strong><button onClick={load}><RefreshCw /> Thử lại</button></div>;
  if (!selected) return <div className="camera-api-state"><CameraOff /><strong>Chưa có camera nào được cấu hình</strong></div>;

  return <section className="smart-camera-page">
    <header className="smart-camera-heading"><div><p>Không gian của bạn</p><h1>Camera</h1></div><span><ShieldCheck /> {feeds.filter((item) => item.status === "online").length}/{feeds.length} camera trực tuyến</span></header>
    <div className="smart-viewer-shell">
      <div className="smart-camera-viewer" key={selected.id}>
        <CameraStream cameraId={selected.id} streamReady={selected.stream_ready} streamUrl={selected.stream_url} playbackUrl={selected.playback_url} />
        {selected.source_kind === "rtsp" && !selected.playback_url && !offline && <div className="smart-camera-offline"><Wifi /><strong>Camera RTSP đã được cấu hình</strong><span>Đang chờ Local Hub cung cấp luồng phát cho trình duyệt</span></div>}
        {offline && <div className="smart-camera-offline"><CameraOff /><strong>Camera đang ngoại tuyến</strong><span>{selected.last_seen_at ? `Lần cuối ${formatTime(selected.last_seen_at)}` : "Chưa có heartbeat"}</span></div>}
        <div className="smart-viewer-top"><span className={`smart-live ${offline ? "offline" : ""}`}><i /><span>{offline ? "Ngoại tuyến" : "Trực tiếp"}</span></span></div>
        <div className="smart-viewer-bottom"><div><strong>{selected.name}</strong><span>{selected.location}</span></div><time>{selected.last_seen_at ? formatTime(selected.last_seen_at) : "—"}</time></div>
      </div>

      <div className="camera-selector-wrap"><header><h2>Camera khác</h2><div><button onClick={() => moveCarousel(-1)}><ChevronLeft /></button><button onClick={() => moveCarousel(1)}><ChevronRight /></button></div></header>
        <div className="camera-selector" ref={selectorRef}>{feeds.map((feed) => <button key={feed.id} className={selected.id === feed.id ? "active" : ""} onClick={() => setSelectedId(feed.id)}><VideoThumbnail feed={feed} /><span className="thumbnail-camera-info"><strong>{feed.name}</strong><small><i className={feed.status !== "online" ? "offline" : ""} />{feed.status === "online" ? "Trực tuyến" : "Ngoại tuyến"}</small></span></button>)}</div>
      </div>

      <section className="smart-camera-actions"><button onClick={() => navigate(`/camera/${encodeURIComponent(selected.id)}`)} className="primary"><Info /><span><strong>Chi tiết camera</strong><small>Trạng thái và lịch sử sự kiện</small></span></button></section>

      <section className="viewer-recent-events"><header><div><h2>Sự kiện hôm nay</h2><p>Dữ liệu thật được lưu trong SQLite cho {selected.name.toLocaleLowerCase("vi")}.</p></div><button onClick={() => navigate(`/camera/${encodeURIComponent(selected.id)}`)}>Xem lịch sử <ChevronRight /></button></header><div>{todayEvents.length ? todayEvents.map((event) => <EventRow key={event.id} event={event} onOpen={() => navigate(`/camera/${encodeURIComponent(selected.id)}?event=${encodeURIComponent(event.event_id)}`)} />) : <p className="viewer-events-empty">Hôm nay camera này chưa ghi nhận sự kiện.</p>}</div></section>
    </div>
  </section>;
}

function EventRow({ event, onOpen }: { event: CameraEventDto; onOpen: () => void }) {
  const fall = event.event_type.includes("FALL") || event.event_type === "fall_suspected";
  const Icon = fall ? AlertTriangle : event.event_type.includes("CAMERA") ? Wifi : Video;
  return <button className={`viewer-event-row ${fall ? "danger" : "info"}`} onClick={onOpen}><time>{formatTime(event.occurred_at)}</time><span><Icon /></span><div><strong>{event.title}</strong><small>{event.description}</small></div><ChevronRight /></button>;
}

function VideoThumbnail({ feed }: { feed: CameraDto }) {
  return <span className={`video-thumbnail ${feed.status !== "online" ? "offline" : ""}`}>
    {feed.stream_ready || feed.playback_url ? <CameraStream cameraId={feed.id} streamReady={feed.stream_ready} streamUrl={feed.stream_url} playbackUrl={feed.playback_url} /> : <span className="camera-source-placeholder"><Camera /></span>}
    <span className={`thumbnail-status ${feed.status !== "online" ? "offline" : ""}`}><i />{feed.status === "online" ? "Trực tiếp" : "Ngoại tuyến"}</span><span className="thumbnail-name">{feed.name}</span>
  </span>;
}

function isToday(value: string): boolean { const date = new Date(value); const now = new Date(); return date.toDateString() === now.toDateString(); }
function formatTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }); }
