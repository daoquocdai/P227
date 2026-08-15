import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Activity, AlertTriangle, BellRing, CheckCircle2, Clock3, Cpu, Gauge, HardDrive, Radio, Server, Wifi, XCircle } from "lucide-react";
import { getStatistics, type StatisticsData, type StatisticsPeriod, type TrendMetric } from "../api/metrics";
import "./statistics.css";

const format = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 1 });

function Trend({ metric }: { metric: TrendMetric }) {
  if (metric.change_percent == null) return null;
  return <small className={`stats-trend ${metric.improved ? "good" : "bad"}`}>{metric.change_percent >= 0 ? "↑" : "↓"} {format.format(Math.abs(metric.change_percent))}% so với kỳ trước</small>;
}

function Kpi({ icon, label, value, metric, tone = "blue", urgent = false }: { icon: ReactNode; label: string; value: string; metric: TrendMetric; tone?: string; urgent?: boolean }) {
  return <article className={`statistics-kpi ${tone}`}><span>{icon}</span><div><strong>{value}{urgent && <AlertTriangle className="kpi-urgent" aria-label="Backlog cần xử lý gấp" />}</strong><p>{label}</p><Trend metric={metric} /></div></article>;
}

function AlertChart({ rows, filter }: { rows: StatisticsData["alert_timeline"]; filter: string }) {
  const selected = rows.filter((row) => filter === "all" || row.alert_type === filter);
  const values = Array.from(new Set(selected.map((row) => row.day))).map((day) => selected.filter((row) => row.day === day).reduce((sum, row) => ({ day, confirmed: sum.confirmed + row.confirmed, false: sum.false + row.false_alarms, total: sum.total + row.total }), { day, confirmed: 0, false: 0, total: 0 }));
  const max = Math.max(1, ...values.map((item) => item.total));
  if (!values.length) return <div className="statistics-empty">Chưa có cảnh báo trong khoảng thời gian này.</div>;
  return <div className="alert-bars" role="img" aria-label="Biểu đồ cảnh báo theo ngày">{values.map((item) => <div className="alert-bar-column" key={item.day}><b>{item.total}</b><div className="stacked-bar"><i className="confirmed" style={{ height: `${item.confirmed / max * 100}%` }} /><i className="false" style={{ height: `${item.false / max * 100}%` }} /><i className="unreviewed" style={{ height: `${Math.max(0, item.total - item.confirmed - item.false) / max * 100}%` }} /></div><time>{new Date(item.day).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" })}</time></div>)}</div>;
}

function LineChart({ rows }: { rows: StatisticsData["performance_timeline"] }) {
  const points = rows.slice(-40); const width = 720; const height = 210;
  if (points.length < 2) return <div className="statistics-empty">Chưa đủ dữ liệu FPS/độ trễ để vẽ xu hướng.</div>;
  const makePath = (key: "fps" | "latency_ms", max: number) => points.map((point, index) => `${index ? "L" : "M"}${index / (points.length - 1) * width},${height - (point[key] ?? 0) / max * (height - 20)}`).join(" ");
  return <div className="line-chart-scroll"><svg viewBox={`0 0 ${width} ${height}`}><path className="grid-line" d={`M0,${height / 2}H${width} M0,${height - 1}H${width}`} /><path className="fps-line" d={makePath("fps", Math.max(30, ...points.map((p) => p.fps ?? 0)))} /><path className="latency-line" d={makePath("latency_ms", Math.max(100, ...points.map((p) => p.latency_ms ?? 0)))} /></svg></div>;
}

function Progress({ value }: { value: number | null }) {
  if (value == null) return <div className="metric-progress skeleton" aria-label="Chưa có dữ liệu" />;
  const percent = Math.max(0, Math.min(100, value ?? 0));
  return <div className="metric-progress"><i className={percent > 90 ? "danger" : ""} style={{ width: `${percent}%` }} /></div>;
}

export default function StatisticsPage() {
  const [period, setPeriod] = useState<StatisticsPeriod>("7d"); const [custom, setCustom] = useState({ start: "", end: "" });
  const [filter, setFilter] = useState("all"); const [data, setData] = useState<StatisticsData | null>(null);
  const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  useEffect(() => { if (period === "custom" && (!custom.start || !custom.end)) return; setLoading(true); setError(""); getStatistics(period, custom.start, custom.end).then(setData).catch((reason: Error) => setError(reason.message)).finally(() => setLoading(false)); }, [period, custom.start, custom.end]);
  const cameraMax = useMemo(() => Math.max(1, ...(data?.camera_distribution.map((item) => item.alert_count) ?? [1])), [data]);
  const k = data?.kpis;
  return <div className="statistics-page">
    <header className="statistics-header"><div><h1>Thống kê</h1><p>Theo dõi hiệu quả cảnh báo và tình trạng vận hành hệ thống.</p></div><div className="statistics-range">{(["today", "7d", "30d", "custom"] as StatisticsPeriod[]).map((item) => <button className={period === item ? "active" : ""} key={item} onClick={() => setPeriod(item)}>{({ today: "Hôm nay", "7d": "7 ngày", "30d": "30 ngày", custom: "Tuỳ chọn" })[item]}</button>)}</div></header>
    {period === "custom" && <div className="custom-range"><label>Từ ngày<input type="date" value={custom.start} onChange={(event) => setCustom({ ...custom, start: event.target.value })} /></label><label>Đến ngày<input type="date" value={custom.end} onChange={(event) => setCustom({ ...custom, end: event.target.value })} /></label></div>}
    {error && <div className="statistics-error"><AlertTriangle />{error}</div>}
    {loading && !data ? <div className="statistics-loading">Đang tổng hợp dữ liệu…</div> : data && k ? <>
      {(() => { const cameras = data.devices.filter((device) => device.id !== "hub"); const disconnected = cameras.filter((device) => device.operational_status === "offline" || device.operational_status === "error").length; return cameras.length > 0 && disconnected / cameras.length >= .5 ? <div className="offline-banner"><AlertTriangle /><span><strong>{disconnected}/{cameras.length} camera đang mất kết nối</strong><small>Hệ thống có thể không phát hiện được sự kiện. Kiểm tra kết nối ngay.</small></span><button onClick={() => { window.history.pushState({}, "", "/settings"); window.dispatchEvent(new PopStateEvent("popstate")); }}>Xem chi tiết camera</button></div> : null; })()}
      <section className="statistics-kpis"><Kpi icon={<BellRing />} label="Tổng số cảnh báo" value={format.format(k.total_alerts.value)} metric={k.total_alerts} /><Kpi icon={<CheckCircle2 />} label="Báo động đúng" value={format.format(k.true_alerts.value)} metric={k.true_alerts} tone="green" /><Kpi icon={<XCircle />} label="Báo động giả" value={format.format(k.false_alerts.value)} metric={k.false_alerts} tone="red" /><Kpi icon={<AlertTriangle />} label="Chưa xác nhận" value={format.format(k.unconfirmed_alerts.value)} metric={k.unconfirmed_alerts} tone="orange" urgent={k.total_alerts.value > 0 && k.unconfirmed_alerts.value / k.total_alerts.value > .5} /><Kpi icon={<Gauge />} label="Tỷ lệ báo động giả" value={`${format.format(k.false_alarm_rate.value * 100)}%`} metric={k.false_alarm_rate} /><Kpi icon={<Clock3 />} label="Phản hồi trung bình" value={`${format.format(k.average_response_ms.value / 1000)} giây`} metric={k.average_response_ms} /></section>
      <section className="statistics-grid"><article className="statistics-card"><div className="statistics-card-heading"><div><h2>Cảnh báo theo thời gian</h2><p>Kết quả xác nhận của người dùng.</p></div><div className="chart-toggle">{[["all", "Tất cả"], ["fall", "Té ngã"], ["unknown_person", "Người lạ"]].map(([value, label]) => <button className={filter === value ? "active" : ""} onClick={() => setFilter(value)} key={value}>{label}</button>)}</div></div><div className="chart-legend"><span><i className="confirmed" />Đúng</span><span><i className="false" />Báo động giả</span><span><i className="unreviewed" />Chưa xác nhận</span></div><AlertChart rows={data.alert_timeline} filter={filter} /></article>
        <article className="statistics-card"><div className="statistics-card-heading"><div><h2>Phân bổ theo camera</h2><p>Số cảnh báo và tỷ lệ nhiễu.</p></div></div><div className="camera-stats">{data.camera_distribution.map((camera) => { const total = data.camera_distribution.reduce((sum, item) => sum + item.alert_count, 0); const abnormal = total > 0 && camera.alert_count / total > .7; return <div key={camera.id}><header><span><strong>{camera.name}{abnormal && <em className="abnormal-badge" title="Camera này tạo ra số cảnh báo vượt trội so với các camera khác — nên kiểm tra.">Bất thường</em>}</strong><small>{camera.location}</small></span><b>{camera.alert_count} · {format.format(camera.false_alarm_rate * 100)}% giả</b></header><div><i style={{ width: `${camera.alert_count / cameraMax * 100}%` }} /></div></div>; })}</div></article>
        {data.false_alarm_reasons.length > 0 && <article className="statistics-card"><div className="statistics-card-heading"><div><h2>Nguyên nhân báo động giả</h2><p>Ghi chú phổ biến khi xác nhận.</p></div></div><ol className="reason-list">{data.false_alarm_reasons.map((item) => <li key={item.note}><span>{item.note}</span><b>{item.count}</b></li>)}</ol></article>}
      </section>
      <section className="performance-section"><div className="performance-title"><span><Activity /></span><div><h2>Hiệu năng vận hành</h2><p>Chỉ số mới nhất của từng camera và xu hướng xử lý.</p></div></div>{data.threshold_alerts.map((alert) => <div className="threshold-banner" key={alert.camera_id}><AlertTriangle /><span><strong>{alert.camera_name} đang hoạt động chậm</strong><small>{alert.reasons.join(" · ")} — có thể ảnh hưởng đến độ chính xác phát hiện.</small></span></div>)}
        <div className="device-grid">{data.devices.map((device) => { const ram = device.ram_total_mb ? (device.ram_usage_mb ?? 0) / device.ram_total_mb * 100 : null; const noData = device.fps == null && device.latency_ms == null && device.ping_ms == null && ram == null && device.cpu_usage_percent == null; return <article className={`device-card ${noData ? "no-data" : ""}`} key={device.id}><header><span className={`device-status ${device.operational_status}`}><Radio /></span><div><h3>{device.name}</h3><p>{device.location_label}</p></div><b className={device.operational_status}>{device.operational_status}</b></header><div className="device-metrics"><span><Gauge /><small>FPS</small><strong className={device.fps == null ? "missing-value" : ""}>{device.fps == null ? "—" : format.format(device.fps)}</strong></span><span><Clock3 /><small>Độ trễ</small><strong className={device.latency_ms == null ? "missing-value" : ""}>{device.latency_ms == null ? "—" : `${format.format(device.latency_ms)} ms`}</strong></span><span><Wifi /><small>Ping</small><strong className={device.ping_ms == null ? "missing-value" : device.ping_ms < 50 ? "ping-good" : device.ping_ms <= 150 ? "ping-warn" : "ping-bad"}>{device.ping_ms == null ? "—" : `${format.format(device.ping_ms)} ms`}</strong></span></div><div className="resource-row"><label><span><Server />RAM</span><b className={ram == null ? "missing-value" : ""}>{ram == null ? "Chưa có dữ liệu" : `${format.format(ram)}%`}</b></label><Progress value={ram} /></div><div className="resource-row"><label><span><Cpu />CPU</span><b className={device.cpu_usage_percent == null ? "missing-value" : ""}>{device.cpu_usage_percent == null ? "Chưa có dữ liệu" : `${format.format(device.cpu_usage_percent)}%`}</b></label><Progress value={device.cpu_usage_percent} /></div><footer className={!device.last_seen_at ? "missing-value" : ""}><HardDrive /> Lần cuối: {device.last_seen_at ? new Date(device.last_seen_at).toLocaleString("vi-VN") : "chưa có dữ liệu"}</footer></article>; })}</div>
        <article className="statistics-card performance-chart"><div className="statistics-card-heading"><div><h2>Xu hướng FPS và độ trễ</h2><p>40 mẫu gần nhất trong khoảng đã chọn.</p></div><div className="chart-legend"><span><i className="fps" />FPS</span><span><i className="latency" />Độ trễ</span></div></div><LineChart rows={data.performance_timeline} /></article>
      </section>
    </> : null}
  </div>;
}
