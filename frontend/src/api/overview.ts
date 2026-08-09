import { apiClient } from "./client";

interface OverviewAlertPayload {
  id: string;
  event_type: string;
  timestamp: string;
  description: string;
  camera_location: string;
  identity_name?: string | null;
  severity?: "low" | "medium" | "high" | "critical";
}

interface OverviewPayload {
  generated_at: string;
  system_status: "safe" | "attention";
  headline: string;
  summary: string;
  metrics: {
    online_cameras: number;
    total_cameras: number;
    events_today: number;
    pending_alerts: number;
    recognized_people_today: number;
  };
  current_alert: OverviewAlertPayload | null;
  cameras: Array<{
    id: string;
    name: string;
    location: string;
    status: "connecting" | "online" | "offline" | "ended" | "error";
    last_seen_at?: string | null;
    source_type: "webcam" | "video_file" | "rtsp";
    playback_url?: string | null;
    stream_url: string;
    stream_ready: boolean;
    preview_url?: string | null;
    preview_version?: number | null;
    vision_enabled: boolean;
    vision_status?: "disabled" | "waiting_for_source" | "running" | "error" | null;
  }>;
  insights: string[];
}

export interface OverviewData {
  generatedAt: string;
  systemStatus: "safe" | "attention";
  headline: string;
  summary: string;
  metrics: {
    onlineCameras: number;
    totalCameras: number;
    eventsToday: number;
    pendingAlerts: number;
    recognizedPeopleToday: number;
  };
  currentAlert: null | {
    id: string;
    title: string;
    subject: string;
    location: string;
    occurredAt: string;
    preview: string;
  };
  cameras: Array<{
    id: string;
    name: string;
    location: string;
    status: "connecting" | "online" | "offline" | "ended" | "error";
    lastSeenAt?: string | null;
    playbackUrl?: string | null;
    streamUrl: string;
    streamReady: boolean;
    previewUrl?: string | null;
    previewVersion?: number | null;
    visionEnabled: boolean;
    visionStatus?: "disabled" | "waiting_for_source" | "running" | "error" | null;
  }>;
  insights: string[];
}

function alertTitle(eventType: string): string {
  if (eventType.includes("FALL")) return "Có khả năng té ngã";
  if (eventType.includes("UNKNOWN")) return "Có người lạ xuất hiện";
  return "Sự kiện cần kiểm tra";
}

export async function getOverview(): Promise<OverviewData> {
  const data = await apiClient<OverviewPayload>("/overview");
  return {
    generatedAt: data.generated_at,
    systemStatus: data.system_status,
    headline: data.headline,
    summary: data.summary,
    metrics: {
      onlineCameras: data.metrics.online_cameras,
      totalCameras: data.metrics.total_cameras,
      eventsToday: data.metrics.events_today,
      pendingAlerts: data.metrics.pending_alerts,
      recognizedPeopleToday: data.metrics.recognized_people_today,
    },
    currentAlert: data.current_alert ? {
      id: data.current_alert.id,
      title: alertTitle(data.current_alert.event_type),
      subject: data.current_alert.identity_name ?? "Camera gia đình",
      location: data.current_alert.camera_location,
      occurredAt: data.current_alert.timestamp,
      preview: data.current_alert.description,
    } : null,
    cameras: data.cameras.map((camera) => ({
      id: camera.id,
      name: camera.name,
      location: camera.location,
      status: camera.status,
      lastSeenAt: camera.last_seen_at,
      playbackUrl: camera.playback_url,
      streamUrl: camera.stream_url,
      streamReady: camera.stream_ready,
      previewUrl: camera.preview_url,
      previewVersion: camera.preview_version,
      visionEnabled: camera.vision_enabled,
      visionStatus: camera.vision_status,
    })),
    insights: data.insights,
  };
}
