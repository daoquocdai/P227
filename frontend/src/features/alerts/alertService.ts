import { apiClient } from "../../api/client";
import type { AlertEvent, AlertSeverity, AlertStatus, AlertType } from "./alert.types";

interface BackendAlert {
  id: string;
  event_id: string;
  timestamp: string;
  event_type: string;
  description: string;
  camera_id?: string;
  camera_location?: string;
  confidence?: number | null;
  identity_name?: string | null;
  immobile_seconds?: number | null;
  snapshot_url?: string | null;
  status?: string | null;
  feedback?: string | null;
  severity: AlertSeverity;
  review_note?: string | null;
  created_at: string;
  updated_at: string;
  is_read: boolean;
  agent_status?: "queued" | "running" | "completed" | "failed" | "skipped" | null;
  agent_verdict?: "CONFIRMED_ALERT" | "UNCERTAIN" | "DUPLICATE" | null;
  agent_reason_summary?: string | null;
  incident_id?: string | null;
  incident_status?: "OPEN" | "ACKNOWLEDGED" | "RESOLVED_SAFE" | null;
  occurrence_count?: number;
  first_seen_at?: string;
  last_seen_at?: string;
  acknowledged_at?: string | null;
  resolved_at?: string | null;
}

const statusValues: AlertStatus[] = ["pending", "checking", "resolved", "safe", "false_alarm", "need_help"];

function eventPresentation(eventType: string): { type: AlertType; title: string; severity: AlertSeverity } {
  const normalized = eventType.toUpperCase();
  if (normalized.includes("FALL")) return { type: "fall", title: "Có khả năng té ngã", severity: "high" };
  if (normalized.includes("UNKNOWN") || normalized.includes("INTRUDER")) return { type: "stranger", title: "Có người lạ xuất hiện", severity: "critical" };
  if (normalized.includes("INACTIVITY") || normalized.includes("IMMOBILE")) return { type: "inactivity", title: "Không phát hiện hoạt động", severity: "medium" };
  if (normalized.includes("ARRIVAL") || normalized.includes("RECOGNIZED")) return { type: "arrival", title: "Người thân đã về nhà", severity: "info" };
  return { type: "camera", title: "Sự kiện camera", severity: "info" };
}

function normalizeStatus(value?: string | null): AlertStatus {
  return statusValues.includes(value as AlertStatus) ? value as AlertStatus : "pending";
}

function toIsoTimestamp(value: string): string {
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? new Date().toISOString() : parsed.toISOString();
}

function toAlertEvent(alert: BackendAlert): AlertEvent {
  const presentation = eventPresentation(alert.event_type);
  const occurredAt = toIsoTimestamp(alert.timestamp);
  const confidence = alert.confidence == null ? undefined : Math.round(alert.confidence <= 1 ? alert.confidence * 100 : alert.confidence);

  return {
    id: String(alert.id), eventId: alert.event_id ?? String(alert.id), cameraId: alert.camera_id ?? "unknown-camera", occurredAt,
    type: presentation.type, title: presentation.title,
    subject: alert.identity_name ?? (presentation.type === "stranger" ? "Người chưa nhận diện" : presentation.type === "fall" ? "Người trong khu vực" : "Không xác định"),
    location: alert.camera_location ?? "Khu vực chưa xác định",
    time: new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit" }).format(new Date(occurredAt)),
    timestamp: occurredAt, severity: alert.severity ?? presentation.severity, status: normalizeStatus(alert.status),
    unread: !alert.is_read, preview: alert.description, confidence,
    immobileSeconds: alert.immobile_seconds ?? undefined, snapshotUrl: alert.snapshot_url ?? undefined,
    reviewNote: alert.review_note ?? undefined,
    agentStatus: alert.agent_status ?? undefined,
    agentVerdict: alert.agent_verdict ?? undefined,
    agentReasonSummary: alert.agent_reason_summary ?? undefined,
    incidentId: alert.incident_id ?? undefined, incidentStatus: alert.incident_status ?? undefined,
    occurrenceCount: alert.occurrence_count ?? 1,
    firstSeenAt: toIsoTimestamp(alert.first_seen_at ?? alert.timestamp),
    lastSeenAt: toIsoTimestamp(alert.last_seen_at ?? alert.timestamp),
    acknowledgedAt: alert.acknowledged_at ?? undefined, resolvedAt: alert.resolved_at ?? undefined,
  };
}

export async function fetchAlerts(): Promise<AlertEvent[]> {
  return (await apiClient<BackendAlert[]>("/alerts")).map(toAlertEvent);
}

export async function updateAlertStatus(id: string, status: AlertStatus, note?: string): Promise<AlertEvent> {
  const alert = await apiClient<BackendAlert>(`/alerts/${encodeURIComponent(id)}`, {
    method: "PATCH", body: JSON.stringify({ status, note }),
  });
  return toAlertEvent(alert);
}

export async function fetchAlert(id: string): Promise<AlertEvent> {
  return toAlertEvent(await apiClient<BackendAlert>(`/alerts/${encodeURIComponent(id)}`));
}

export async function markAlertRead(id: string): Promise<AlertEvent> {
  return toAlertEvent(await apiClient<BackendAlert>(`/alerts/${encodeURIComponent(id)}/read`, { method: "POST" }));
}
