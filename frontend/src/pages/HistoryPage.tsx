import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle, CalendarDays, Camera, Check, ChevronDown, ChevronLeft, ChevronRight, Clock3,
  Eye, History, Image, MapPin, PersonStanding, RefreshCw, RotateCcw, Search, ShieldAlert, User,
  UserRoundCheck, UserRoundX, UsersRound, X,
} from "lucide-react";
import "./history.css";
import { getHistory } from "../api/history";

type EventKind = "person_detected" | "fall_suspected";
type AlertStatus = "open" | "acknowledged" | "resolved" | "dismissed";
type Severity = "low" | "medium" | "high" | "critical";
type Verdict = "true_positive" | "false_positive" | "uncertain";

type HistoryAction = {
  id: string;
  actor: string;
  action: string;
  note?: string;
  verdict?: Verdict;
  at: string;
};

type HistoryMedia = {
  id: string;
  subjectType: "known_person" | "unknown_person" | "fall" | "scene";
  isBlurred: boolean;
  label: string;
  url?: string;
};

type HistoryEvent = {
  id: string;
  kind: EventKind;
  cameraId: string;
  cameraName: string;
  location: string;
  occurredAt: string;
  endedAt?: string;
  confidence: number;
  model: string;
  modelVersion: string;
  person?: { id: string; name: string };
  unknown?: boolean;
  fall?: { posture: string; immobilityMs: number; confidence: number };
  alert?: { severity: Severity; status: AlertStatus };
  verdict?: Verdict;
  media: HistoryMedia[];
  actions: HistoryAction[];
};

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const initialEvents: HistoryEvent[] = [
  {
    id: "evt-001", kind: "fall_suspected", cameraId: "cam-living", cameraName: "Camera phòng khách", location: "Phòng khách",
    occurredAt: ago(5), endedAt: ago(4.7), confidence: .91, model: "AnTam Fall Detection", modelVersion: "1.2.0",
    person: { id: "person-lan", name: "Bà Lan" }, fall: { posture: "Nằm", immobilityMs: 12_000, confidence: .91 },
    alert: { severity: "critical", status: "open" }, media: [
      { id: "m-1", subjectType: "scene", isBlurred: false, label: "Toàn cảnh phòng khách" },
      { id: "m-2", subjectType: "fall", isBlurred: false, label: "Khoảnh khắc phát hiện" },
    ], actions: [{ id: "a-1", actor: "Hệ thống AI", action: "Đã tạo cảnh báo khẩn cấp", at: ago(5) }],
  },
  {
    id: "evt-002", kind: "person_detected", cameraId: "cam-door", cameraName: "Camera cửa chính", location: "Lối vào",
    occurredAt: ago(18), endedAt: ago(17), confidence: .84, model: "AnTam Face Recognition", modelVersion: "2.0.1",
    unknown: true, alert: { severity: "high", status: "acknowledged" }, media: [
      { id: "m-3", subjectType: "unknown_person", isBlurred: true, label: "Người chưa xác định · đã làm mờ" },
      { id: "m-4", subjectType: "scene", isBlurred: false, label: "Toàn cảnh lối vào" },
    ], actions: [
      { id: "a-2", actor: "Hệ thống AI", action: "Đã tạo cảnh báo người lạ", at: ago(18) },
      { id: "a-3", actor: "Minh Nguyễn", action: "Đã xác nhận xem cảnh báo", note: "Đang kiểm tra camera cửa chính", at: ago(15) },
    ],
  },
  {
    id: "evt-003", kind: "person_detected", cameraId: "cam-living", cameraName: "Camera phòng khách", location: "Phòng khách",
    occurredAt: ago(47), endedAt: ago(44), confidence: .97, model: "AnTam Face Recognition", modelVersion: "2.0.1",
    person: { id: "person-lan", name: "Bà Lan" }, media: [{ id: "m-5", subjectType: "known_person", isBlurred: false, label: "Bà Lan tại phòng khách" }], actions: [],
  },
  {
    id: "evt-004", kind: "fall_suspected", cameraId: "cam-bedroom", cameraName: "Camera phòng ngủ", location: "Phòng ngủ",
    occurredAt: ago(132), endedAt: ago(131), confidence: .64, model: "AnTam Fall Detection", modelVersion: "1.2.0",
    person: { id: "person-minh", name: "Ông Minh" }, fall: { posture: "Chuyển tư thế", immobilityMs: 1_200, confidence: .64 },
    alert: { severity: "medium", status: "dismissed" }, verdict: "false_positive", media: [{ id: "m-6", subjectType: "fall", isBlurred: false, label: "Khung hình phát hiện" }], actions: [
      { id: "a-4", actor: "Hệ thống AI", action: "Đã tạo cảnh báo té ngã", at: ago(132) },
      { id: "a-5", actor: "Minh Nguyễn", action: "Đã báo cảnh báo sai", note: "Ông chỉ cúi xuống nhặt đồ", verdict: "false_positive", at: ago(127) },
    ],
  },
  {
    id: "evt-005", kind: "person_detected", cameraId: "cam-hall", cameraName: "Camera hành lang", location: "Hành lang tầng 1",
    occurredAt: ago(280), confidence: .95, model: "AnTam Face Recognition", modelVersion: "2.0.1",
    person: { id: "person-minh", name: "Ông Minh" }, media: [{ id: "m-7", subjectType: "scene", isBlurred: false, label: "Hành lang tầng 1" }], actions: [],
  },
  {
    id: "evt-006", kind: "person_detected", cameraId: "cam-door", cameraName: "Camera cửa chính", location: "Lối vào",
    occurredAt: ago(390), confidence: .79, model: "AnTam Face Recognition", modelVersion: "2.0.1",
    unknown: true, alert: { severity: "medium", status: "resolved" }, verdict: "true_positive", media: [{ id: "m-8", subjectType: "unknown_person", isBlurred: true, label: "Người giao hàng · đã làm mờ" }], actions: [
      { id: "a-6", actor: "Hệ thống AI", action: "Đã tạo cảnh báo người lạ", at: ago(390) },
      { id: "a-7", actor: "Mai Anh", action: "Đã xác nhận đúng", note: "Người giao hàng chưa đăng ký", verdict: "true_positive", at: ago(384) },
      { id: "a-8", actor: "Mai Anh", action: "Đã đánh dấu xử lý", at: ago(382) },
    ],
  },
  {
    id: "evt-007", kind: "person_detected", cameraId: "cam-kitchen", cameraName: "Camera bếp", location: "Nhà bếp",
    occurredAt: ago(1_540), confidence: .93, model: "AnTam Face Recognition", modelVersion: "2.0.1",
    person: { id: "person-hoa", name: "Cô Hoa" }, media: [{ id: "m-9", subjectType: "known_person", isBlurred: false, label: "Cô Hoa trong bếp" }], actions: [],
  },
  {
    id: "evt-008", kind: "fall_suspected", cameraId: "cam-living", cameraName: "Camera phòng khách", location: "Phòng khách",
    occurredAt: ago(2_980), confidence: .88, model: "AnTam Fall Detection", modelVersion: "1.1.5",
    person: { id: "person-lan", name: "Bà Lan" }, fall: { posture: "Nằm", immobilityMs: 8_400, confidence: .88 },
    alert: { severity: "high", status: "resolved" }, verdict: "true_positive", media: [{ id: "m-10", subjectType: "fall", isBlurred: false, label: "Khung hình té ngã" }], actions: [
      { id: "a-9", actor: "Hệ thống AI", action: "Đã tạo cảnh báo té ngã", at: ago(2_980) },
      { id: "a-10", actor: "Minh Nguyễn", action: "Đã xác nhận đúng và xử lý", verdict: "true_positive", at: ago(2_974) },
    ],
  },
];

const statusLabels: Record<AlertStatus, string> = { open: "Đang mở", acknowledged: "Đã xác nhận", resolved: "Đã xử lý", dismissed: "Đã bỏ qua" };
const severityLabels: Record<Severity, string> = { low: "Thấp", medium: "Trung bình", high: "Cao", critical: "Khẩn cấp" };
const postureLabels: Record<string, string> = { lying: "Nằm", sitting: "Ngồi", standing: "Đứng", transitioning: "Chuyển tư thế" };

type FilterOption = { value: string; label: string };

function FilterDropdown({ label, icon: Icon, value, options, onChange, align = "left" }: {
  label: string;
  icon: LucideIcon;
  value: string;
  options: FilterOption[];
  onChange: (value: string) => void;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number; width: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const selected = options.find((option) => option.value === value) ?? options[0];

  const placeMenu = useCallback(() => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    const width = Math.max(rect.width, 180);
    const preferredLeft = align === "right" ? rect.right - width : rect.left;
    setPosition({ top: rect.bottom + 6, left: Math.max(10, Math.min(preferredLeft, window.innerWidth - width - 10)), width });
  }, [align]);

  useEffect(() => {
    if (!open) return;
    placeMenu();
    const close = () => setOpen(false);
    const clickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!buttonRef.current?.contains(target) && !menuRef.current?.contains(target)) close();
    };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { close(); buttonRef.current?.focus(); } };
    document.addEventListener("mousedown", clickOutside);
    document.addEventListener("keydown", escape);
    window.addEventListener("resize", placeMenu);
    window.addEventListener("scroll", close, { capture: true, passive: true, once: true });
    return () => {
      document.removeEventListener("mousedown", clickOutside);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("resize", placeMenu);
      window.removeEventListener("scroll", close, true);
    };
  }, [open, placeMenu]);

  return <div className="filter-dropdown">
    <button ref={buttonRef} type="button" className={`filter-dropdown-trigger ${open ? "is-open" : ""}`} aria-label={label} aria-haspopup="listbox" aria-expanded={open} onClick={() => { if (!open) placeMenu(); setOpen((current) => !current); }}>
      <Icon /><span>{selected.label}</span><ChevronDown />
    </button>
    {open && position && createPortal(<div ref={menuRef} className="filter-dropdown-menu" role="listbox" aria-label={label} style={{ top: position.top, left: position.left, width: position.width }}>
      <div className="filter-dropdown-menu-title"><span>{label}</span><small>Chọn một giá trị</small></div>
      <div className="filter-dropdown-options">{options.map((option) => <button type="button" role="option" aria-selected={option.value === value} className={option.value === value ? "is-selected" : ""} key={option.value} onClick={() => { onChange(option.value); setOpen(false); buttonRef.current?.focus(); }}><span className="filter-option-label"><i />{option.label}</span><span className="filter-option-check">{option.value === value && <Check />}</span></button>)}</div>
    </div>, document.body)}
  </div>;
}

function relativeTime(iso: string) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60_000));
  if (minutes < 1) return "Vừa xong";
  if (minutes < 60) return `${minutes} phút trước`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} giờ trước`;
  const days = Math.floor(hours / 24);
  return `${days} ngày trước`;
}

function fullTime(iso: string) {
  return new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "medium" }).format(new Date(iso));
}

function tableTime(iso: string) {
  return new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit", year: "numeric" }).format(new Date(iso)).replace(",", " -");
}

function normalizeSearchText(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLocaleLowerCase("vi")
    .trim();
}

function parseLocalDateBoundary(value: string, endOfDay: boolean): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;

  const year = Number(match[1]);
  const month = Number(match[2]) - 1;
  const day = Number(match[3]);
  const date = new Date(year, month, day, endOfDay ? 23 : 0, endOfDay ? 59 : 0, endOfDay ? 59 : 0, endOfDay ? 999 : 0);

  if (date.getFullYear() !== year || date.getMonth() !== month || date.getDate() !== day) return null;
  return date.getTime();
}

function HistoryThumbnail({ media, kind }: { media?: HistoryMedia; kind: EventKind }) {
  const unknown = media?.subjectType === "unknown_person";
  return <div className={`history-thumbnail ${kind === "fall_suspected" ? "is-fall" : ""} ${unknown ? "is-unknown" : ""}`}>
    <div className={unknown && media?.isBlurred ? "privacy-blur" : ""}>
      {media?.url ? <img src={media.url} alt={media.label} /> : <>{kind === "fall_suspected" ? <PersonStanding /> : unknown ? <UserRoundX /> : <UserRoundCheck />}<span>{kind === "fall_suspected" ? "Phát hiện tư thế" : unknown ? "Ảnh đã làm mờ" : "Ảnh nhận diện"}</span></>}
    </div>
    {unknown && <small><ShieldAlert /> Riêng tư</small>}
  </div>;
}

export default function HistoryPage() {
  const [events, setEvents] = useState<HistoryEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [range, setRange] = useState("7d");
  const [kind, setKind] = useState("all");
  const [cameraId, setCameraId] = useState("all");
  const [status, setStatus] = useState("all");
  const [person, setPerson] = useState("all");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selected, setSelected] = useState<HistoryEvent | null>(null);
  const [lightboxMedia, setLightboxMedia] = useState<HistoryMedia | null>(null);
  const loadHistory = () => { setLoading(true); setLoadError(false); getHistory().then((items) => setEvents(items as HistoryEvent[])).catch(() => setLoadError(true)).finally(() => setLoading(false)); };
  useEffect(loadHistory, []);

  const cameras = useMemo(() => Array.from(new Map(events.map((event) => [event.cameraId, { id: event.cameraId, name: event.cameraName }])).values()), [events]);
  const persons = useMemo(() => Array.from(new Map(events.flatMap((event) => event.person ? [[event.person.id, event.person] as const] : [])).values()), [events]);

  const filtered = useMemo(() => {
    const customStart = customFrom ? parseLocalDateBoundary(customFrom, false) : null;
    const customEnd = customTo ? parseLocalDateBoundary(customTo, true) : null;
    const invalidCustomRange = (Boolean(customFrom) && customStart === null) || (Boolean(customTo) && customEnd === null);
    const keyword = normalizeSearchText(search);
    const now = Date.now();

    return events.filter((event) => {
      const occurredAt = Date.parse(event.occurredAt);
      if (!Number.isFinite(occurredAt)) return false;

      const age = now - occurredAt;
      const withinRange = range === "today" ? age >= 0 && age <= 86_400_000 : range === "7d" ? age >= 0 && age <= 7 * 86_400_000 : range === "30d" ? age >= 0 && age <= 30 * 86_400_000 : true;
      const withinCustom = range !== "custom" || (!invalidCustomRange && (customStart === null || occurredAt >= customStart) && (customEnd === null || occurredAt <= customEnd));
      const searchableText = normalizeSearchText([
        event.person?.name ?? (event.unknown ? "Người lạ" : ""),
        event.cameraName,
        event.location,
      ].join(" "));
      const matchesSearch = !keyword || searchableText.includes(keyword);
      return withinRange && withinCustom && matchesSearch
        && (kind === "all" || event.kind === kind)
        && (cameraId === "all" || event.cameraId === cameraId)
        && (status === "all" || event.alert?.status === status)
        && (person === "all" || (person === "unknown" ? event.unknown : event.person?.id === person));
    }).sort((a, b) => Date.parse(b.occurredAt) - Date.parse(a.occurredAt));
  }, [events, range, customFrom, customTo, kind, cameraId, status, person, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageItems = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const pageStart = filtered.length ? (currentPage - 1) * pageSize + 1 : 0;
  const pageEnd = Math.min(currentPage * pageSize, filtered.length);
  const changeFilter = (setter: (value: string) => void, value: string) => { setter(value); setPage(1); };
  const resetFilters = () => { setRange("7d"); setKind("all"); setCameraId("all"); setStatus("all"); setPerson("all"); setSearch(""); setCustomFrom(""); setCustomTo(""); setPage(1); };
  if (loading) return <div className="history-page page-wrap"><section className="history-empty"><span><RefreshCw /></span><h2>Đang tải lịch sử…</h2></section></div>;
  if (loadError) return <div className="history-page page-wrap"><section className="history-empty"><span><AlertTriangle /></span><h2>Không tải được lịch sử</h2><p>Hãy kiểm tra kết nối tới backend Local Hub.</p><div><button onClick={loadHistory}>Thử lại</button></div></section></div>;
  return <div className="history-page page-wrap">
    <div className="history-heading">
      <div className="history-title-line"><h1>Lịch sử</h1><i /><p>Theo dõi những gì camera đã ghi nhận và cách gia đình xử lý cảnh báo.</p></div>
      <div className="history-total"><History /><span><strong>{filtered.length}</strong><small>sự kiện phù hợp</small></span></div>
    </div>

    <section className="history-filter-panel" aria-label="Bộ lọc lịch sử">
      <div className="history-filters">
        <div className="history-search"><Search /><input value={search} onChange={(e) => changeFilter(setSearch, e.target.value)} placeholder="Tìm người, camera..." aria-label="Tìm kiếm lịch sử" />{search && <button onClick={() => changeFilter(setSearch, "")} aria-label="Xoá tìm kiếm"><X /></button>}</div>
        <FilterDropdown label="Khoảng thời gian" icon={CalendarDays} value={range} onChange={(value) => changeFilter(setRange, value)} options={[{ value: "today", label: "Hôm nay" }, { value: "7d", label: "7 ngày qua" }, { value: "30d", label: "30 ngày qua" }, { value: "custom", label: "Tuỳ chọn" }]} />
        <FilterDropdown label="Loại sự kiện" icon={History} value={kind} onChange={(value) => changeFilter(setKind, value)} options={[{ value: "all", label: "Tất cả sự kiện" }, { value: "person_detected", label: "Phát hiện người" }, { value: "fall_suspected", label: "Nghi ngờ té ngã" }]} />
        <FilterDropdown label="Camera" icon={Camera} value={cameraId} onChange={(value) => changeFilter(setCameraId, value)} options={[{ value: "all", label: "Tất cả camera" }, ...cameras.map((item) => ({ value: item.id, label: item.name }))]} />
        <FilterDropdown label="Trạng thái cảnh báo" icon={ShieldAlert} value={status} onChange={(value) => changeFilter(setStatus, value)} options={[{ value: "all", label: "Tất cả trạng thái" }, { value: "open", label: "Đang mở" }, { value: "acknowledged", label: "Đã xác nhận" }, { value: "resolved", label: "Đã xử lý" }, { value: "dismissed", label: "Đã bỏ qua" }]} />
        <FilterDropdown label="Người liên quan" icon={UsersRound} value={person} align="right" onChange={(value) => changeFilter(setPerson, value)} options={[{ value: "all", label: "Tất cả mọi người" }, { value: "unknown", label: "Người lạ" }, ...persons.map((item) => ({ value: item.id, label: item.name }))]} />
        <button className="compact-reset" onClick={resetFilters} title="Đặt lại bộ lọc"><RotateCcw /> <span>Đặt lại</span></button>
      </div>
      {range === "custom" && <div className="custom-date-range"><label><span>Từ ngày</span><input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} /></label><span>đến</span><label><span>Đến ngày</span><input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} /></label></div>}
    </section>

    {filtered.length ? <>
      <div className="history-list-heading"><div><span className="live-dot" /> Mới nhất trước</div><small>Sắp xếp theo occurred_at DESC</small></div>
      <div className="history-table-wrap">
        <table className="history-table">
          <thead><tr><th>Ảnh</th><th>Thời gian</th><th>Loại sự kiện</th><th>Đối tượng</th><th>Camera / Vị trí</th><th className="confidence-column">Độ tin cậy AI</th><th>Trạng thái</th><th>Mức độ</th><th><span className="sr-only">Hành động</span></th></tr></thead>
          <tbody>{pageItems.map((event) => {
            const media = event.media.find((item) => item.subjectType === "scene") ?? event.media[0];
            const critical = event.alert?.severity === "critical" && event.alert.status === "open";
            return <tr key={event.id} className={`${critical ? "critical-open" : ""} ${event.verdict === "false_positive" ? "false-positive-row" : ""}`} onClick={() => setSelected(event)} tabIndex={0} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setSelected(event)}>
              <td><div className="table-thumb"><HistoryThumbnail media={media} kind={event.kind} /></div></td>
              <td><time title={fullTime(event.occurredAt)}>{tableTime(event.occurredAt)}</time><small>{relativeTime(event.occurredAt)}</small></td>
              <td><span className={`event-kind table-kind ${event.kind === "fall_suspected" ? "fall" : "person"}`}>{event.kind === "fall_suspected" ? <AlertTriangle /> : <User />}{event.kind === "fall_suspected" ? "Nghi ngờ té ngã" : "Phát hiện người"}</span></td>
              <td><strong className={event.unknown ? "unknown-person" : ""}>{event.person?.name ?? "Người lạ"}</strong>{event.verdict && <span className={`table-verdict ${event.verdict}`}>{event.verdict === "false_positive" ? "Báo động giả" : "Đã xác nhận đúng"}</span>}</td>
              <td><strong>{event.cameraName}</strong><small>{event.location}</small></td>
              <td className="confidence-column"><div className="confidence-value"><span><i style={{ width: `${event.confidence * 100}%` }} /></span><strong>{Math.round(event.confidence * 100)}%</strong></div></td>
              <td>{event.alert ? <span className={`alert-status ${event.alert.status}`}>{statusLabels[event.alert.status]}</span> : <span className="alert-status not-applicable">Không áp dụng</span>}</td>
              <td>{event.alert ? <span className={`severity-dot ${event.alert.severity}`} title={severityLabels[event.alert.severity]}><i />{severityLabels[event.alert.severity]}</span> : <span className="severity-dot not-applicable"><i />—</span>}</td>
              <td><button className="row-action" title="Xem chi tiết" aria-label={`Xem chi tiết ${event.id}`} onClick={(e) => { e.stopPropagation(); setSelected(event); }}><Eye /></button></td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      <section className="history-mobile-list">{pageItems.map((event) => {
        const media = event.media.find((item) => item.subjectType === "scene") ?? event.media[0];
        const critical = event.alert?.severity === "critical" && event.alert.status === "open";
        return <button key={event.id} className={`mobile-history-card ${critical ? "critical-open" : ""} ${event.verdict === "false_positive" ? "false-positive-row" : ""}`} onClick={() => setSelected(event)}>
          <div className="mobile-card-thumb"><HistoryThumbnail media={media} kind={event.kind} /></div>
          <div><span className={`event-kind ${event.kind === "fall_suspected" ? "fall" : "person"}`}>{event.kind === "fall_suspected" ? <AlertTriangle /> : <User />}{event.kind === "fall_suspected" ? "Nghi ngờ té ngã" : "Phát hiện người"}</span><strong className={event.unknown ? "unknown-person" : ""}>{event.person?.name ?? "Người lạ"}</strong><small>{tableTime(event.occurredAt)} · {event.cameraName}</small><span>{event.location}</span></div>
          {event.alert && <span className={`alert-status ${event.alert.status}`}>{statusLabels[event.alert.status]}</span>}
        </button>;
      })}</section>
      <div className="history-pagination"><div>Hiển thị <strong>{pageStart}-{pageEnd}</strong> trong tổng <strong>{filtered.length}</strong> sự kiện</div><label>Số dòng<select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}><option value={10}>10</option><option value={20}>20</option><option value={50}>50</option></select></label><nav aria-label="Phân trang"><button disabled={currentPage === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft /><span>Trước</span></button><span className="mobile-page-indicator">Trang {currentPage}/{totalPages}</span>{Array.from({ length: totalPages }, (_, index) => index + 1).map((number) => <button key={number} className={`page-number ${number === currentPage ? "active" : ""}`} onClick={() => setPage(number)} aria-current={number === currentPage ? "page" : undefined}>{number}</button>)}<button disabled={currentPage === totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}><span>Sau</span><ChevronRight /></button></nav></div>
    </> : <section className="history-empty"><span><History /></span><h2>Chưa có sự kiện phù hợp</h2><p>Thử thay đổi bộ lọc hoặc quay lại camera để theo dõi hoạt động mới.</p><div><button onClick={resetFilters}>Xoá bộ lọc</button><a href="/camera">Xem camera</a></div></section>}

    {selected && <div className="history-modal-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && setSelected(null)}>
      <article className="history-detail-modal" role="dialog" aria-modal="true" aria-labelledby="history-detail-title">
        <header><div><span className={selected.kind === "fall_suspected" ? "danger" : "safe"}>{selected.kind === "fall_suspected" ? <AlertTriangle /> : <User />}</span><div><small>CHI TIẾT SỰ KIỆN</small><h2 id="history-detail-title">{selected.kind === "fall_suspected" ? "Nghi ngờ té ngã" : "Phát hiện người"}</h2></div></div><button aria-label="Đóng" onClick={() => setSelected(null)}><X /></button></header>
        <div className="history-modal-content">
          <section className="antam-analysis"><span><ShieldAlert /></span><div><small>PHÂN TÍCH CỦA AN TÂM</small><h3>{selected.kind === "fall_suspected" ? "Hệ thống ghi nhận một thay đổi tư thế có khả năng là té ngã." : selected.unknown ? "Hệ thống ghi nhận một người chưa có trong danh sách người thân." : `Hệ thống nhận diện ${selected.person?.name ?? "người thân"} xuất hiện trong khu vực theo dõi.`}</h3><p>{selected.kind === "fall_suspected" ? `Độ tin cậy ${Math.round(selected.confidence * 100)}%. Dữ liệu này là kết quả AI ban đầu và được giữ nguyên để phục vụ đối soát.` : `Sự kiện được camera ${selected.cameraName} ghi nhận với độ tin cậy ${Math.round(selected.confidence * 100)}%.`}</p></div></section>
          <section className="quick-analysis"><div className="detail-section-title"><History /><h3>Phân tích nhanh</h3></div><div><span><small>Khả năng</small><strong>{Math.round(selected.confidence * 100)}%</strong></span><span><small>Người</small><strong>{selected.person?.name ?? "Người lạ"}</strong></span><span><small>Camera</small><strong>{selected.cameraName}</strong></span><span><small>Thời gian</small><strong>{tableTime(selected.occurredAt)}</strong></span></div></section>
          <section><div className="detail-section-title"><Image /><h3>Ảnh sự kiện</h3><span>{selected.media.length} ảnh</span></div><div className="media-gallery">{selected.media.map((media) => <div key={media.id}><HistoryThumbnail media={media} kind={selected.kind} /><div className="media-caption"><p>{media.label}</p><button onClick={() => setLightboxMedia(media)}><Eye /> Xem ảnh</button></div></div>)}</div></section>
          <div className="detail-grid">
            <section className="detail-info-card"><h3>Thông tin phát hiện</h3><dl><div><dt>Người liên quan</dt><dd>{selected.person?.name ?? "Người lạ"}</dd></div><div><dt>Camera</dt><dd>{selected.cameraName}</dd></div><div><dt>Vị trí</dt><dd>{selected.location}</dd></div><div><dt>Thời gian</dt><dd>{fullTime(selected.occurredAt)}</dd></div>{selected.fall && <><div><dt>Tư thế</dt><dd>{selected.fall.posture}</dd></div><div><dt>Bất động</dt><dd>{selected.fall.immobilityMs / 1000} giây</dd></div></>}</dl></section>
            <section className="detail-info-card ai-card"><h3>Thông tin AI</h3><div className="confidence-ring" style={{ "--confidence": `${selected.confidence * 100}%` } as React.CSSProperties}><strong>{Math.round(selected.confidence * 100)}%</strong><small>tin cậy</small></div><dl><div><dt>Mô hình</dt><dd>{selected.model}</dd></div><div><dt>Phiên bản</dt><dd>{selected.modelVersion}</dd></div></dl></section>
          </div>
          {selected.alert && <section><div className="detail-section-title"><Clock3 /><h3>Lịch sử xử lý</h3></div><div className="action-timeline">{selected.actions.map((action) => <div key={action.id}><i /><div><header><strong>{action.action}</strong><time>{relativeTime(action.at)}</time></header><p>{action.actor}</p>{action.note && <blockquote>“{action.note}”</blockquote>}{action.verdict && <span className={`verdict-badge ${action.verdict}`}>{action.verdict === "false_positive" ? "Cảnh báo sai" : "Xác nhận đúng"}</span>}</div></div>)}</div></section>}
        </div>
        <footer className="readonly-modal-note"><ShieldAlert /><span>Đây là màn hình chỉ xem dành cho admin. Xử lý cảnh báo được thực hiện bởi caregiver qua ứng dụng riêng.</span></footer>
      </article>
    </div>}
    {lightboxMedia && selected && <div className="history-lightbox" role="dialog" aria-modal="true" aria-label="Xem ảnh sự kiện" onMouseDown={(event) => event.target === event.currentTarget && setLightboxMedia(null)}><button aria-label="Đóng ảnh" title="Đóng" onClick={() => setLightboxMedia(null)}><X /></button><div><HistoryThumbnail media={lightboxMedia} kind={selected.kind} /><p>{lightboxMedia.label}</p>{lightboxMedia.subjectType === "unknown_person" && <small><ShieldAlert /> Ảnh người lạ luôn được bảo vệ bằng hiệu ứng làm mờ.</small>}</div></div>}
  </div>;
}
