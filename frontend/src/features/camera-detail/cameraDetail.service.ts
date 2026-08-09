import { getCamera, type CameraDto, type CameraEventDto } from "../../api/cameras";
import type { CameraDetail, CameraEvent, CameraEventStatus, CameraEventType } from "./cameraDetail.types";

export async function fetchCameraDetail(cameraId: string): Promise<{ camera: CameraDetail; events: CameraEvent[] }> {
  const data = await getCamera(cameraId);
  return { camera: toCameraDetail(data), events: (data.events ?? []).map((event) => toCameraEvent(data.id, event)) };
}

function toCameraDetail(camera: CameraDto): CameraDetail {
  return {
    id: camera.id, name: camera.name, room: camera.location,
    status: camera.status === "online" ? "online" : "offline",
    quality: "HD", lastUpdatedAt: camera.last_seen_at ?? new Date().toISOString(),
    videoUrl: camera.playback_url ?? "", streamUrl: camera.stream_url, streamReady: camera.stream_ready,
    monitoringStatus: camera.active ? "active" : "paused",
    safetyStatus: (camera.events ?? []).some((event) => event.status === "open") ? "attention" : "safe",
  };
}

function toCameraEvent(cameraId: string, event: CameraEventDto): CameraEvent {
  const date = new Date(event.occurred_at);
  return {
    id: event.id, eventId: event.event_id, cameraId, type: eventType(event.event_type), title: event.title,
    description: event.description,
    occurredAt: date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }),
    dayGroup: dayGroup(date), severity: event.severity === "critical" ? "high" : event.severity === "medium" ? "warning" : "info",
    status: eventStatus(event.status), confidence: event.confidence == null ? undefined : Math.round(event.confidence * 100),
    isRead: event.status !== "open",
  };
}

function eventType(value: string): CameraEventType {
  const normalized = value.toUpperCase();
  if (normalized.includes("FALL")) return "fall_detection";
  if (normalized.includes("UNKNOWN")) return "unknown_person";
  if (normalized.includes("RECOGNIZED")) return "member_recognized";
  if (normalized.includes("INACTIVITY")) return "immobility";
  if (normalized.includes("OFFLINE")) return "camera_offline";
  if (normalized.includes("ONLINE")) return "camera_online";
  return "person_detected";
}

function eventStatus(value: CameraEventDto["status"]): CameraEventStatus {
  return { open: "new", acknowledged: "need_help", resolved: "reviewed", dismissed: "safe" }[value] as CameraEventStatus;
}

function dayGroup(date: Date): CameraEvent["dayGroup"] {
  const today = new Date();
  const difference = Math.floor((new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime() - new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()) / 86_400_000);
  return difference === 0 ? "Hôm nay" : difference === 1 ? "Hôm qua" : "28 tháng 7";
}
