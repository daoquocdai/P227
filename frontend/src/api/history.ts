import { apiClient } from "./client";

interface HistoryPayload {
  items: Array<{
    id: string; kind: "person_detected" | "fall_suspected"; camera_id: string; camera_name: string;
    location: string; occurred_at: string; ended_at?: string | null; confidence: number; model: string;
    model_version: string; person?: { id: string; name: string } | null; unknown: boolean;
    fall?: { posture: string; immobility_ms: number; confidence: number } | null;
    alert?: { id: string; severity: "low" | "medium" | "high" | "critical"; status: "open" | "acknowledged" | "resolved" | "dismissed" } | null;
    verdict?: "true_positive" | "false_positive" | "uncertain" | null;
    media: Array<{ id: string; subject_type: "known_person" | "unknown_person" | "fall" | "scene"; is_blurred: boolean; label: string; url?: string }>;
    actions: Array<{ id: string; actor: string; action: string; note?: string | null; verdict?: "true_positive" | "false_positive" | "uncertain" | null; at: string }>;
  }>;
}

export async function getHistory() {
  const data = await apiClient<HistoryPayload>("/history");
  return data.items.map((event) => ({
    id: event.id, kind: event.kind, cameraId: event.camera_id, cameraName: event.camera_name,
    location: event.location, occurredAt: event.occurred_at, endedAt: event.ended_at ?? undefined,
    confidence: event.confidence, model: event.model, modelVersion: event.model_version,
    person: event.person ?? undefined, unknown: event.unknown,
    fall: event.fall ? { posture: event.fall.posture, immobilityMs: event.fall.immobility_ms, confidence: event.fall.confidence } : undefined,
    alert: event.alert ? { severity: event.alert.severity, status: event.alert.status } : undefined,
    verdict: event.verdict ?? undefined,
    media: event.media.map((item) => ({ id: item.id, subjectType: item.subject_type, isBlurred: item.is_blurred, label: item.label, url: item.url })),
    actions: event.actions.map((item) => ({ id: item.id, actor: item.actor, action: item.action, note: item.note ?? undefined, verdict: item.verdict ?? undefined, at: item.at })),
  }));
}
