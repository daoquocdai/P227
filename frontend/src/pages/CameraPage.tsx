import { AlertTriangle, Camera, CameraOff, ChevronLeft, ChevronRight, Edit3, Expand, Minimize, RefreshCw, ShieldCheck, Trash2, Video, Wifi, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { deleteCamera, getCamera, getCameras, updateCamera, type CameraDto, type CameraEventDto } from "../api/cameras";
import { CameraStream } from "../components";
import "./cameraViewer.css";
import "./cameraApi.css";

export default function CameraPage() {
  const [feeds, setFeeds] = useState<CameraDto[]>([]);
  const [selectedId, setSelectedId] = useState(() => new URLSearchParams(window.location.search).get("camera") ?? "");
  const [events, setEvents] = useState<CameraEventDto[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState("");
  const [fullscreen, setFullscreen] = useState(false);
  const selectorRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const camerasRequestInFlight = useRef(false);

  const load = async () => {
    if (camerasRequestInFlight.current) return;
    camerasRequestInFlight.current = true;
    setLoading(true); setError(false);
    try { const items=await getCameras(); setFeeds(items); setSelectedId((current) => items.some((item) => item.id === current) ? current : items[0]?.id || ""); }
    catch { setError(true); }
    finally { camerasRequestInFlight.current = false; setLoading(false); }
  };
  useEffect(() => { void load(); }, []);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible" || camerasRequestInFlight.current) return;
      camerasRequestInFlight.current = true;
      void getCameras().then(setFeeds).catch(() => undefined).finally(() => { camerasRequestInFlight.current = false; });
    }, 5_000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(()=>{const sync=()=>setFullscreen(document.fullscreenElement===viewerRef.current);document.addEventListener("fullscreenchange",sync);return()=>document.removeEventListener("fullscreenchange",sync)},[]);
  useEffect(() => {
    if (!selectedId) return;
    getCamera(selectedId).then((camera) => setEvents(camera.events ?? [])).catch(() => setEvents([]));
  }, [selectedId]);

  const selected = feeds.find((feed) => feed.id === selectedId);
  const todayEvents = events.filter((event) => isToday(event.occurred_at));
  const offline = !selected || selected.status !== "online";
  const navigate = (path: string) => { window.history.pushState({}, "", path); window.dispatchEvent(new PopStateEvent("popstate")); };
  const moveCarousel = (direction: -1 | 1) => selectorRef.current?.scrollBy({ left: direction * 220, behavior: "smooth" });
  const toggleFullscreen = () => void (document.fullscreenElement ? document.exitFullscreen() : viewerRef.current?.requestFullscreen());
  const saveCamera = async (event:FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if(!selected||saving)return; setActionError(""); setSaving(true);
    const form=new FormData(event.currentTarget); const source_kind=String(form.get("source_kind")) as CameraDto["source_kind"];
    const source_uri=String(form.get("source_uri")||"").trim();
    const playback_path=source_kind==="video_file"?source_uri:undefined;
    try{await updateCamera(selected.id,{name:String(form.get("name")),location:String(form.get("location")),source_kind,source_uri,playback_path});await load();setEditing(false);}
    catch(saveError){console.error("Không thể lưu camera",saveError);setActionError("Không thể lưu camera. Kiểm tra tên và nguồn phát.")}
    finally{setSaving(false)}
  };
  const removeCamera=async()=>{if(!selected||selected.active)return;setActionError("");try{await deleteCamera(selected.id);setEditing(false);setSelectedId("");load();}catch{setActionError("Không thể xóa camera. Camera phải được tắt trong Cài đặt và không còn lịch sử liên quan.")}};

  if (loading) return <div className="camera-api-state"><ShieldCheck /><strong>Đang tải camera từ Local Hub…</strong></div>;
  if (error) return <div className="camera-api-state error"><CameraOff /><strong>Không kết nối được backend</strong><button onClick={load}><RefreshCw /> Thử lại</button></div>;
  if (!selected) return <div className="camera-api-state"><CameraOff /><strong>Chưa có camera nào được cấu hình</strong></div>;

  return <section className="smart-camera-page">
    <header className="smart-camera-heading"><div><p>Không gian của bạn</p><h1>Camera</h1></div><span><ShieldCheck /> {feeds.filter((item) => item.status === "online").length}/{feeds.length} camera trực tuyến</span></header>
    <div className="smart-viewer-shell">
      <div className="smart-camera-viewer" key={selected.id} ref={viewerRef}>
        <CameraStream cameraId={selected.id} streamReady={selected.stream_ready} streamUrl={selected.stream_url} />
        {selected.source_kind === "rtsp" && !selected.playback_url && !offline && <div className="smart-camera-offline"><Wifi /><strong>Camera RTSP đã được cấu hình</strong><span>Đang chờ Local Hub cung cấp luồng phát cho trình duyệt</span></div>}
        {offline && <div className="smart-camera-offline"><CameraOff /><strong>{selected.status === "error" ? "Không thể mở camera" : "Camera đang ngoại tuyến"}</strong><span>{selected.error ?? (selected.last_seen_at ? `Lần cuối ${formatTime(selected.last_seen_at)}` : "Chưa có heartbeat")}</span></div>}
        <div className="smart-viewer-top"><span className={`smart-live ${offline ? "offline" : ""}`}><i /><span>{offline ? "Ngoại tuyến" : "Trực tiếp"}</span></span><button className="camera-fullscreen-button" onClick={toggleFullscreen} aria-label={fullscreen?"Thu nhỏ camera":"Phóng to toàn màn hình"} title={fullscreen?"Thoát toàn màn hình":"Toàn màn hình"}>{fullscreen?<Minimize/>:<Expand/>}</button></div>
        <div className="smart-viewer-bottom"><div><strong>{selected.name}</strong><span>{selected.location} · {selected.source}</span></div><time>{selected.last_seen_at ? formatTime(selected.last_seen_at) : "—"}</time></div>
      </div>

      <div className="camera-selector-wrap"><header><h2>Camera khác</h2><div><button onClick={() => moveCarousel(-1)}><ChevronLeft /></button><button onClick={() => moveCarousel(1)}><ChevronRight /></button></div></header>
        <div className="camera-selector" ref={selectorRef}>{feeds.filter((feed)=>feed.id!==selected.id).map((feed) => <button key={feed.id} onClick={() => setSelectedId(feed.id)}><VideoThumbnail feed={feed} /><span className="thumbnail-camera-info"><strong>{feed.location||"Chưa đặt vị trí"}</strong><small><i className={feed.status !== "online" ? "offline" : ""} />{feed.status === "online" ? "Trực tuyến" : "Ngoại tuyến"}</small></span></button>)}</div>
      </div>

      <section className="smart-camera-actions"><button className="primary" onClick={()=>setEditing(true)}><Edit3/><span><strong>Chi tiết camera</strong><small>Chỉnh sửa tên, vị trí và nguồn phát</small></span></button><div className="camera-readonly-state"><ShieldCheck/><span><strong>{selected.active?"Camera đang bật":"Camera đang tắt"}</strong><small>Vision: {selected.vision_status??"disabled"} · Bật/tắt trong Cài đặt</small></span></div></section>

      <section className="viewer-recent-events"><header><div><h2>Sự kiện hôm nay</h2><p>Dữ liệu thật được lưu trong SQLite cho {selected.name.toLocaleLowerCase("vi")}.</p></div><button onClick={() => navigate("/history")}>Xem lịch sử <ChevronRight /></button></header><div>{todayEvents.length ? todayEvents.map((event) => <EventRow key={event.id} event={event} onOpen={() => navigate("/history")} />) : <p className="viewer-events-empty">Hôm nay camera này chưa ghi nhận sự kiện.</p>}</div></section>
    </div>
    {editing&&<div className="camera-edit-backdrop"><form className="camera-edit-modal" onSubmit={saveCamera}><header><div><h2>Chi tiết camera</h2><p>Thay đổi được lưu trong SQLite.</p></div><button type="button" disabled={saving} onClick={()=>setEditing(false)}><X/></button></header>{actionError&&<p className="camera-edit-error">{actionError}</p>}<label><span>Tên camera</span><input name="name" defaultValue={selected.name} required maxLength={255}/></label><label><span>Vị trí</span><input name="location" defaultValue={selected.location} required maxLength={255}/></label><label><span>Loại nguồn</span><select name="source_kind" defaultValue={selected.source_kind}><option value="video_file">Video file</option><option value="webcam">Webcam</option><option value="rtsp">RTSP</option></select></label><label><span>Nguồn phát</span><input name="source_uri" defaultValue={editableSource(selected)} placeholder={selected.source_kind==="rtsp"?"rtsp://…":"Đường dẫn video hoặc webcam index"} required/></label><footer><button type="button" className="camera-delete" disabled={selected.active||saving} onClick={()=>void removeCamera()}><Trash2/> Xóa camera</button><button type="button" disabled={saving} onClick={()=>setEditing(false)}>Hủy</button><button type="submit" disabled={saving}>{saving?"Đang lưu…":"Lưu thay đổi"}</button></footer>{selected.active&&<small className="camera-delete-note">Muốn xóa, hãy tắt camera trong Cài đặt trước.</small>}</form></div>}
  </section>;
}

function EventRow({ event, onOpen }: { event: CameraEventDto; onOpen: () => void }) {
  const fall = event.event_type.includes("FALL") || event.event_type === "fall_suspected";
  const Icon = fall ? AlertTriangle : event.event_type.includes("CAMERA") ? Wifi : Video;
  return <button className={`viewer-event-row ${fall ? "danger" : "info"}`} onClick={onOpen}><time>{formatTime(event.occurred_at)}</time><span><Icon /></span><div><strong>{event.title}</strong><small>{event.description}</small></div><ChevronRight /></button>;
}

function VideoThumbnail({ feed }: { feed: CameraDto }) {
  const [failed,setFailed]=useState(false);
  return <span className={`video-thumbnail ${feed.status !== "online" ? "offline" : ""}`}>
    {feed.stream_ready&&!failed?<CameraStream cameraId={feed.id} streamReady streamUrl={feed.stream_url} onError={()=>setFailed(true)}/>:<span className="camera-source-placeholder"><Camera /></span>}
    <span className={`thumbnail-status ${feed.status !== "online" ? "offline" : ""}`}><i />{feed.status === "online" ? "Trực tiếp" : "Ngoại tuyến"}</span><span className="thumbnail-name">{feed.name}</span>
  </span>;
}

function editableSource(camera:CameraDto):string{if(camera.source_kind==="rtsp")return "";if(camera.source_kind==="webcam")return camera.source.replace(/^Webcam\s*/i,"");return camera.source}

function isToday(value: string): boolean { const date = new Date(value); const now = new Date(); return date.toDateString() === now.toDateString(); }
function formatTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }); }
