import { useEffect, useMemo, useState } from "react";
import { AlertConversation } from "./AlertConversation";
import { AlertList } from "./AlertList";
import { fetchAlerts, markAlertRead, updateAlertStatus } from "./alertService";
import type { AlertEvent, AlertFilter } from "./alert.types";
import "./alerts.css";
import "./snapshotApi.css";

export default function AlertsPage() {
  const routeAlertId = () => decodeURIComponent(window.location.pathname.split("/")[2] ?? "");
  const initialRouteAlertId = routeAlertId();
  const [alerts, setAlerts] = useState<AlertEvent[]>([]); const [selectedId, setSelectedId] = useState(initialRouteAlertId); const [search, setSearch] = useState(""); const [filter, setFilter] = useState<AlertFilter>("all"); const [loading, setLoading] = useState(true); const [error, setError] = useState(false); const [mobileConversation, setMobileConversation] = useState(Boolean(initialRouteAlertId));
  useEffect(() => {
    document.documentElement.classList.add("alerts-viewport-locked");
    document.body.classList.add("alerts-viewport-locked");
    return () => {
      document.documentElement.classList.remove("alerts-viewport-locked");
      document.body.classList.remove("alerts-viewport-locked");
    };
  }, []);
  useEffect(() => {
    document.body.classList.toggle("alerts-conversation-open", mobileConversation);
    return () => document.body.classList.remove("alerts-conversation-open");
  }, [mobileConversation]);
  useEffect(() => {
    if (!mobileConversation || !selectedId) return;
    const selectedAlert = alerts.find((item) => item.id === selectedId);
    if (!selectedAlert?.unread) return;
    setAlerts((items) => items.map((item) => item.id === selectedId ? { ...item, unread: false } : item));
    void markAlertRead(selectedId).then((updated) => {
      setAlerts((items) => items.map((item) => item.id === selectedId ? updated : item));
      window.dispatchEvent(new CustomEvent("antam:alerts-changed"));
    }).catch(() => setAlerts((items) => items.map((item) => item.id === selectedId ? { ...item, unread: true } : item)));
  }, [alerts, mobileConversation, selectedId]);
  useEffect(() => {
    const syncAlertRoute = () => {
      const id = routeAlertId();
      setSelectedId(id);
      setMobileConversation(Boolean(id));
    };
    window.addEventListener("popstate", syncAlertRoute);
    return () => window.removeEventListener("popstate", syncAlertRoute);
  }, []);
  const load = () => { setLoading(true); setError(false); fetchAlerts().then((items) => { setAlerts(items); setSelectedId((current) => items.some((item) => item.id === current) ? current : items[0]?.id || ""); }).catch(() => setError(true)).finally(() => setLoading(false)); };
  useEffect(load, []);
  useEffect(() => {
    const syncAlerts = () => { void fetchAlerts().then(setAlerts).catch(() => undefined); };
    window.addEventListener("antam:alerts-changed", syncAlerts);
    return () => window.removeEventListener("antam:alerts-changed", syncAlerts);
  }, []);
  const visibleAlerts = useMemo(() => alerts.filter((alert) => { const query = search.trim().toLocaleLowerCase("vi"); const matchesSearch = !query || `${alert.title} ${alert.subject} ${alert.location}`.toLocaleLowerCase("vi").includes(query); const matchesFilter = filter === "all" || (filter === "pending" && ["pending", "checking", "need_help"].includes(alert.status)) || (filter === "critical" && alert.severity === "critical") || (filter === "resolved" && ["resolved", "safe", "false_alarm"].includes(alert.status)); return matchesSearch && matchesFilter; }), [alerts, search, filter]);
  const selected = alerts.find((alert) => alert.id === selectedId) ?? alerts[0];
  const selectAlert = (id: string) => { window.history.pushState({}, "", `/alerts/${encodeURIComponent(id)}`); setSelectedId(id); setAlerts((items) => items.map((item) => item.id === id ? { ...item, unread: false } : item)); setMobileConversation(true); };
  const backToList = () => { window.history.pushState({}, "", "/alerts"); setMobileConversation(false); };
  const updateStatus = (status: AlertEvent["status"], note?: string) => {
    if (!selected) return;
    const targetId = selected.id;
    const previousStatus = selected.status;
    setAlerts((items) => items.map((item) => item.id === targetId ? { ...item, status, unread: false } : item));
    window.dispatchEvent(new CustomEvent("antam:alert-status", { detail: { id: targetId, status } }));
    void updateAlertStatus(targetId, status, note).then((updated) => {
      setAlerts((items) => items.map((item) => item.id === targetId ? updated : item));
    }).catch(() => {
      setAlerts((items) => items.map((item) => item.id === targetId ? { ...item, status: previousStatus } : item));
      window.alert("Không thể lưu trạng thái cảnh báo. Vui lòng kiểm tra kết nối backend.");
    });
  };
  return <section className={`alerts-page ${mobileConversation ? "conversation-open" : ""}`}>
    <div className="alerts-workspace"><AlertList alerts={visibleAlerts} selectedId={selectedId} loading={loading} error={error} search={search} filter={filter} onSearch={setSearch} onFilter={setFilter} onSelect={selectAlert} onRetry={load} />{selected ? <AlertConversation key={selected.id} alert={selected} onBack={backToList} onStatus={updateStatus} /> : <div className="alerts-empty">Chọn một cảnh báo để bắt đầu.</div>}</div>
  </section>;
}
