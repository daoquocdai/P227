import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Activity, AlertTriangle, BellRing, CheckCircle2, Clock3, Cpu, Gauge, HardDrive, Radio, Server, XCircle } from "lucide-react";
import { getStatistics, type CameraMetric, type StatisticsData, type StatisticsPeriod, type TrendMetric } from "../api/metrics";
import "./statistics.css";

const number = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 1 });
const periods: Array<[StatisticsPeriod, string]> = [["today", "Hôm nay"], ["7d", "7 ngày"], ["30d", "30 ngày"], ["custom", "Tuỳ chọn"]];
const value = (metric: TrendMetric, suffix = "") => metric.value == null ? "—" : `${number.format(metric.value)}${suffix}`;
const vietnamDateTime = (timestamp: string) => new Date(timestamp).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" });

export function formatResponseTime(milliseconds: number | null) {
  if (milliseconds == null) return "—";
  const seconds = milliseconds / 1000;
  if (seconds < 60) return `${number.format(seconds)} giây`;
  const roundedSeconds = Math.round(seconds);
  if (roundedSeconds < 3600) return `${Math.floor(roundedSeconds / 60)} phút ${roundedSeconds % 60} giây`;
  return `${Math.floor(roundedSeconds / 3600)} giờ ${Math.floor((roundedSeconds % 3600) / 60)} phút`;
}

function Trend({ metric }: { metric: TrendMetric }) {
  if (metric.change_percent == null) return <small className="stats-missing">Chưa có kỳ so sánh</small>;
  return <small className={`stats-trend ${metric.improved ? "good" : "bad"}`}>{metric.change_percent >= 0 ? "↑" : "↓"} {number.format(Math.abs(metric.change_percent))}% so với kỳ trước</small>;
}

function Kpi({ icon, label, display, metric, tone = "blue" }: { icon: ReactNode; label: string; display: string; metric: TrendMetric; tone?: string }) {
  return <article className={`statistics-kpi ${tone}`}><span>{icon}</span><div><strong className={metric.value == null ? "stats-missing" : ""}>{display}</strong><p>{label}</p><Trend metric={metric} /></div></article>;
}

function AlertChart({ rows, filter, bucketUnit }: { rows: StatisticsData["alert_timeline"]; filter: string; bucketUnit: StatisticsData["alert_bucket"]["unit"] }) {
  const selected = rows.filter(row => filter === "all" || row.alert_type === filter);
  const points = Array.from(new Set(selected.map(row => row.bucket_start))).map(bucketStart => selected.filter(row => row.bucket_start === bucketStart).reduce((sum, row) => ({ bucketStart, total: sum.total + row.total, confirmed: sum.confirmed + row.confirmed, falseAlarms: sum.falseAlarms + row.false_alarms }), { bucketStart, total: 0, confirmed: 0, falseAlarms: 0 }));
  const max = Math.max(1, ...points.map(point => point.total));
  const label = (timestamp: string) => new Date(timestamp).toLocaleString("vi-VN", bucketUnit === "hour" ? { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Ho_Chi_Minh" } : { day: "2-digit", month: "2-digit", timeZone: "Asia/Ho_Chi_Minh" });
  return <div className={`alert-bars ${bucketUnit}`} role="img" aria-label={bucketUnit === "hour" ? "Cảnh báo theo giờ" : "Cảnh báo theo ngày"}>{points.map(point => <div className="alert-bar-column" key={point.bucketStart}><b>{point.total}</b><div className="stacked-bar"><i className="confirmed" style={{ height: `${point.confirmed / max * 100}%` }} /><i className="false" style={{ height: `${point.falseAlarms / max * 100}%` }} /><i className="unreviewed" style={{ height: `${Math.max(0, point.total - point.confirmed - point.falseAlarms) / max * 100}%` }} /></div><time dateTime={point.bucketStart}>{label(point.bucketStart)}</time></div>)}</div>;
}

type PerformancePoint = StatisticsData["performance_timeline"][number];

function MetricTrend({ rows, metric, label, unit }: { rows: PerformancePoint[]; metric: "vision_fps" | "vision_processing_latency_ms"; label: string; unit: string }) {
  const width = 560; const height = 145; const chartHeight = 112;
  const max = Math.max(1, ...rows.map(point => point[metric] ?? 0));
  const coordinates = rows.map((point, index) => ({ point, x: index / (rows.length - 1) * width, y: chartHeight - (point[metric] ?? 0) / max * (chartHeight - 10) })).filter(item => item.point[metric] != null);
  const path = coordinates.map((item, index) => `${index ? "L" : "M"}${item.x},${item.y}`).join(" ");
  return <div className="trend-panel"><header><strong>{label}</strong><span>0–{number.format(max)} {unit}</span></header><svg viewBox={`0 0 ${width} ${height}`} aria-label={`${label}, đơn vị ${unit}`}><path className="grid-line" d={`M0,${chartHeight / 2}H${width} M0,${chartHeight}H${width}`} /><path className={metric === "vision_fps" ? "fps-line" : "latency-line"} d={path} />{coordinates.map(({ point, x, y }) => <circle className={metric === "vision_fps" ? "fps-point" : "latency-point"} cx={x} cy={y} r="4" key={`${point.measured_at}-${metric}`}><title>{`${vietnamDateTime(point.measured_at)} · Vision FPS: ${point.vision_fps == null ? "—" : number.format(point.vision_fps)} · Độ trễ: ${point.vision_processing_latency_ms == null ? "—" : `${number.format(point.vision_processing_latency_ms)} ms`} · ${point.bucket_seconds ? `Bucket ${point.bucket_seconds / 60} phút (${point.sample_count} mẫu)` : "Mẫu gốc"}`}</title></circle>)}</svg></div>;
}

function PerformanceChart({ rows }: { rows: PerformancePoint[] }) {
  const valid = rows.filter(point => point.vision_fps != null || point.vision_processing_latency_ms != null);
  if (valid.length === 0) return <div className="statistics-empty trend-empty">Chưa có dữ liệu vận hành.</div>;
  if (valid.length === 1) return <div className="statistics-empty trend-empty">Đã có 1 mẫu vận hành. Cần thêm dữ liệu để vẽ xu hướng.</div>;
  return <div className="performance-trends"><MetricTrend rows={valid} metric="vision_fps" label="Vision FPS" unit="FPS" /><MetricTrend rows={valid} metric="vision_processing_latency_ms" label="Độ trễ Vision" unit="ms" /></div>;
}

const statusLabels: Record<NonNullable<CameraMetric["camera_status"]>, string> = { disabled: "Đang tắt", waiting: "Đang chờ", online: "Trực tuyến", disconnected: "Mất kết nối", error: "Lỗi", ended: "Đã kết thúc" };
const sourceLabels: Record<NonNullable<CameraMetric["source_kind"]>, string> = { video_file: "Video", webcam: "Webcam", rtsp: "RTSP" };

function CameraCard({ camera }: { camera: CameraMetric }) {
  const inactive = camera.camera_status === "disabled" || camera.camera_status === "ended";
  const source = camera.source_kind ? sourceLabels[camera.source_kind] : "Chưa rõ nguồn";
  const fallback = camera.data_source === "runtime" ? null : camera.data_source === "none" ? "Runtime không khả dụng; chưa có mẫu đã lưu." : `Runtime không khả dụng; dùng mẫu đã lưu ${camera.measured_at ? vietnamDateTime(camera.measured_at) : "không rõ thời điểm"}${camera.is_stale ? " (mẫu cũ)" : ""}.`;
  return <article className={`device-card ${inactive ? "inactive" : ""}`}><header><span className={`device-status ${camera.camera_status ?? "disconnected"}`}><Radio /></span><div><h3>{camera.name}</h3><p>{source} · {camera.location_label || "Chưa đặt vị trí"}</p></div><b className={camera.camera_status ?? "disconnected"}>{camera.camera_status ? statusLabels[camera.camera_status] : "Chưa có trạng thái"}</b></header>{fallback && <div className="telemetry-fallback">{fallback}</div>}{inactive ? <div className="camera-inactive-note">Camera được chủ động tắt; không có lỗi kết nối.</div> : <><div className="device-metrics"><span><Gauge /><small>FPS nguồn</small><strong>{camera.raw_fps == null ? "—" : number.format(camera.raw_fps)}</strong></span><span><Activity /><small>Vision FPS</small><strong>{camera.vision_fps == null ? "—" : number.format(camera.vision_fps)}</strong></span><span><Clock3 /><small>Độ trễ Vision</small><strong>{camera.vision_processing_latency_ms == null ? "—" : `${number.format(camera.vision_processing_latency_ms)} ms`}</strong></span><span><XCircle /><small>Ghi đè latest-slot</small><strong>{camera.vision_drop_ratio == null ? "—" : `${number.format(camera.vision_drop_ratio * 100)}%`}</strong></span></div><footer>Vision: {camera.vision_status ?? "chưa có dữ liệu"} · Hàng đợi Vision: {camera.pending ?? "—"}/{camera.max_pending ?? "—"} · Frame gần nhất: {camera.last_seen_at ? vietnamDateTime(camera.last_seen_at) : "—"}</footer></>}</article>;
}

export default function StatisticsPage() {
  const [period, setPeriod] = useState<StatisticsPeriod>("7d");
  const [custom, setCustom] = useState({ start: "", end: "" });
  const [filter, setFilter] = useState("all");
  const [performanceCamera, setPerformanceCamera] = useState("");
  const [data, setData] = useState<StatisticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    if (period === "custom" && (!custom.start || !custom.end)) { setLoading(false); return; }
    setLoading(true); setError("");
    getStatistics(period, custom.start, custom.end).then(setData).catch((reason: Error) => setError(reason.message)).finally(() => setLoading(false));
  }, [period, custom.start, custom.end]);
  const cameraMax = useMemo(() => Math.max(1, ...(data?.camera_distribution.map(item => item.alert_count) ?? [1])), [data]);
  const k = data?.kpis;
  const performanceCameras = data?.performance_series.filter(item => item.sample_count > 0) ?? [];
  const selectedPerformanceCamera = performanceCameras.some(item => item.camera_id === performanceCamera) ? performanceCamera : performanceCameras[0]?.camera_id ?? "";
  const falseAlarmEmpty = k?.false_alerts.value === 0 ? "Chưa có cảnh báo nào được đánh dấu là báo động giả." : "Có báo động giả nhưng chưa có ghi chú nguyên nhân.";
  return <section className="statistics-page">
    <header className="statistics-header"><div><h1>Thống kê</h1><p>Cảnh báo lịch sử và telemetry từ runtime hiện tại.</p></div><div className="statistics-range">{periods.map(([key, label]) => <button className={period === key ? "active" : ""} key={key} onClick={() => setPeriod(key)}>{label}</button>)}</div></header>
    {period === "custom" && <div className="custom-range"><label>Từ ngày<input type="date" value={custom.start} onChange={event => setCustom({ ...custom, start: event.target.value })} /></label><label>Đến ngày<input type="date" min={custom.start} value={custom.end} onChange={event => setCustom({ ...custom, end: event.target.value })} /></label></div>}
    {error && <div className="statistics-error"><AlertTriangle />{error}</div>}
    {loading && !data && <div className="statistics-loading">Đang tổng hợp dữ liệu…</div>}
    {data && k && <>
      <div className="statistics-kpis"><Kpi icon={<BellRing />} label="Tổng cảnh báo" display={value(k.total_alerts)} metric={k.total_alerts} /><Kpi icon={<CheckCircle2 />} label="Đã xác nhận đúng" display={value(k.true_alerts)} metric={k.true_alerts} tone="green" /><Kpi icon={<XCircle />} label="Báo động giả" display={value(k.false_alerts)} metric={k.false_alerts} tone="red" /><Kpi icon={<AlertTriangle />} label="Chưa xác nhận" display={value(k.unconfirmed_alerts)} metric={k.unconfirmed_alerts} tone="orange" /><Kpi icon={<Gauge />} label="Tỷ lệ báo động giả" display={k.false_alarm_rate.value == null ? "—" : `${number.format(k.false_alarm_rate.value * 100)}%`} metric={k.false_alarm_rate} /><Kpi icon={<Clock3 />} label="Phản hồi đầu tiên" display={formatResponseTime(k.average_response_ms.value)} metric={k.average_response_ms} /></div>
      <div className="statistics-grid"><article className="statistics-card"><div className="statistics-card-heading"><div><h2>Cảnh báo theo thời gian</h2><p>Phân loại theo hành động người dùng mới nhất.</p></div><div className="chart-toggle">{[["all", "Tất cả"], ["fall", "Té ngã"], ["unknown_person", "Người lạ"]].map(([key, label]) => <button className={filter === key ? "active" : ""} key={key} onClick={() => setFilter(key)}>{label}</button>)}</div></div><div className="chart-legend"><span><i className="confirmed" />Đúng</span><span><i className="false" />Giả</span><span><i className="unreviewed" />Chưa xác nhận</span></div><AlertChart rows={data.alert_timeline} filter={filter} bucketUnit={data.alert_bucket.unit} /></article>
        <div className="statistics-side-stack"><article className="statistics-card"><div className="statistics-card-heading"><div><h2>Phân bổ theo camera</h2><p>Số cảnh báo và tỷ lệ giả trên các cảnh báo đã review.</p></div></div><div className="camera-stats">{data.camera_distribution.map(camera => <div key={camera.id}><header><span><strong>{camera.name}</strong><small>{camera.location || "Chưa đặt vị trí"}</small></span><b>{camera.alert_count} · {camera.false_alarm_rate == null ? "—" : `${number.format(camera.false_alarm_rate * 100)}% giả`}</b></header><div><i style={{ width: `${camera.alert_count / cameraMax * 100}%` }} /></div></div>)}</div></article>
          <article className="statistics-card"><div className="statistics-card-heading"><div><h2>Nguyên nhân báo động giả</h2><p>Ghi chú từ hành động false alarm mới nhất.</p></div></div>{data.false_alarm_reasons.length ? <ol className="reason-list">{data.false_alarm_reasons.map(item => <li key={item.note}><span>{item.note}</span><b>{item.count}</b></li>)}</ol> : <div className="statistics-empty reason-empty">{falseAlarmEmpty}</div>}</article></div></div>
      <section className="performance-section"><div className="performance-title"><Activity /><div><h2>Hiệu năng vận hành</h2><p>Card camera là realtime; biểu đồ xu hướng dùng mẫu lịch sử đã lưu.</p></div></div>
        <div className="hub-card"><header><Server /><div><h3>Local Hub</h3><p>Telemetry backend process và host</p></div><time>{data.hub_metrics ? `${vietnamDateTime(data.hub_metrics.measured_at)}${data.hub_metrics.is_stale ? " · mẫu cũ" : ""}` : "Chưa có mẫu"}</time></header><div><span><Cpu /><small>CPU backend process</small><strong>{data.hub_metrics?.process_cpu_percent == null ? "—" : `${number.format(data.hub_metrics.process_cpu_percent)}%`}</strong></span><span><Server /><small>RAM backend process</small><strong>{data.hub_metrics?.process_rss_mb == null ? "—" : `${number.format(data.hub_metrics.process_rss_mb)} MB`}</strong></span><span><Gauge /><small>RAM host</small><strong>{data.hub_metrics?.host_memory_used_percent == null ? "—" : `${number.format(data.hub_metrics.host_memory_used_percent)}%`}</strong></span><span><HardDrive /><small>Đĩa host</small><strong>{data.hub_metrics?.disk_used_percent == null ? "—" : `${number.format(data.hub_metrics.disk_used_percent)}%`}</strong></span></div></div>
        {data.threshold_alerts.length > 0 && <div className="operational-warnings">{data.threshold_alerts.map(alert => <div className="threshold-banner" key={`${alert.scope}-${alert.id}`}><AlertTriangle /><span><strong>{alert.name}</strong><small>{alert.reasons.join(" · ")}</small></span></div>)}</div>}
        <div className="device-grid">{data.camera_metrics.map(camera => <CameraCard camera={camera} key={camera.id} />)}</div>
        <article className="statistics-card performance-chart"><div className="statistics-card-heading"><div><h2>Xu hướng Vision FPS và độ trễ</h2><p>Mẫu lịch sử; backend chỉ bucket khi cần giới hạn tối đa 120 điểm/camera.</p></div><div className="performance-chart-controls">{performanceCameras.length > 1 && <select aria-label="Chọn camera cho biểu đồ hiệu năng" value={selectedPerformanceCamera} onChange={event => setPerformanceCamera(event.target.value)}>{performanceCameras.map(item => <option value={item.camera_id} key={item.camera_id}>{item.camera_name}</option>)}</select>}</div></div><PerformanceChart rows={data.performance_timeline.filter(item => item.camera_id === selectedPerformanceCamera)} /></article>
      </section>
    </>}
  </section>;
}
