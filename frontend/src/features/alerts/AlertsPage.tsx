import { useEffect, useMemo, useState } from "react";
import { AlertConversation } from "./AlertConversation";
import { AlertList } from "./AlertList";
import { fetchAlerts, updateAlertStatus } from "./alertService";
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
    const syncAlertRoute = () => {
      const id = routeAlertId();
      setSelectedId(id);
      setMobileConversation(Boolean(id));
    };
    window.addEventListener("popstate", syncAlertRoute);
    return () => window.removeEventListener("popstate", syncAlertRoute);
  }, []);
  const load = () => { setLoading(true); setError(false); fetchAlerts().then((items) => { setAlerts(items); setSelectedId((current) => current || items[0]?.id || ""); }).catch(() => setError(true)).finally(() => setLoading(false)); };
  useEffect(load, []);
  const visibleAlerts = useMemo(() => alerts.filter((alert) => { const query = search.trim().toLocaleLowerCase("vi"); const matchesSearch = !query || `${alert.title} ${alert.subject} ${alert.location}`.toLocaleLowerCase("vi").includes(query); const matchesFilter = filter === "all" || (filter === "pending" && ["pending", "checking", "need_help"].includes(alert.status)) || (filter === "critical" && alert.severity === "critical") || (filter === "resolved" && ["resolved", "safe", "false_alarm"].includes(alert.status)); return matchesSearch && matchesFilter; }), [alerts, search, filter]);
  const selected = alerts.find((alert) => alert.id === selectedId) ?? alerts[0];
  const selectAlert = (id: string) => { window.history.pushState({}, "", `/alerts/${encodeURIComponent(id)}`); setSelectedId(id); setAlerts((items) => items.map((item) => item.id === id ? { ...item, unread: false } : item)); setMobileConversation(true); };
  const backToList = () => { window.history.pushState({}, "", "/alerts"); setMobileConversation(false); };
  const updateStatus = (status: AlertEvent["status"]) => {
    const previousStatus = alerts.find((item) => item.id === selectedId)?.status;
    setAlerts((items) => items.map((item) => item.id === selectedId ? { ...item, status, unread: false } : item));
    window.dispatchEvent(new CustomEvent("antam:alert-status", { detail: { id: selectedId, status } }));
    void updateAlertStatus(selectedId, status).then((updated) => {
      setAlerts((items) => items.map((item) => item.id === selectedId ? updated : item));
    }).catch(() => {
      if (previousStatus) setAlerts((items) => items.map((item) => item.id === selectedId ? { ...item, status: previousStatus } : item));
      window.alert("Không thể lưu trạng thái cảnh báo. Vui lòng kiểm tra kết nối backend.");
    });
  };
  return <section className={`alerts-page ${mobileConversation ? "conversation-open" : ""}`}>
    <div className="alerts-workspace"><AlertList alerts={visibleAlerts} selectedId={selectedId} loading={loading} error={error} search={search} filter={filter} onSearch={setSearch} onFilter={setFilter} onSelect={selectAlert} onRetry={load} />{selected ? <AlertConversation key={selected.id} alert={selected} onBack={backToList} onStatus={updateStatus} /> : <div className="alerts-empty">Chọn một cảnh báo để bắt đầu.</div>}</div>
  </section>;
}
