import { apiClient, apiCommand } from "./client";

export interface CameraEventDto {
  id: string;
  event_id: string;
  event_type: string;
  title: string;
  description: string;
  occurred_at: string;
  severity: "low" | "medium" | "high" | "critical";
  status: "open" | "acknowledged" | "resolved" | "dismissed";
  confidence?: number | null;
}

export interface CameraDto {
  id: string;
  name: string;
  location: string;
  status: "connecting" | "online" | "offline" | "ended" | "error";
  error?: string | null;
  last_seen_at?: string | null;
  active: boolean;
  vision_enabled: boolean;
  vision_status?: "disabled" | "waiting_for_source" | "running" | "error" | null;
  source_kind: "video_file" | "webcam" | "rtsp";
  source: string;
  playback_url?: string | null;
  stream_url: string;
  stream_ready: boolean;
  preview_url?: string | null;
  preview_version?: number | null;
  events?: CameraEventDto[];
}

export interface CameraVisionDetection {
  label: string;
  confidence: number;
  bbox_xyxy?: [number, number, number, number] | null;
  metadata: Record<string, unknown>;
}

export interface CameraVisionMetadata extends Record<string, unknown> {
  bbox_coordinate_space?: string;
  bbox_source_width?: number;
  bbox_source_height?: number;
  current_action?: string;
  action_class_id?: number | null;
  action_class_name?: "fall" | "standing" | "bending" | "sitting" | "lying" | null;
  action_label?: "Ngã" | "Đứng" | "Cúi" | "Ngồi" | "Nằm" | null;
  action_confidence?: number | null;
  fall_state?: string;
  fall_confidence?: number | null;
}

export interface CameraVisionResult {
  camera_id: string;
  frame_id: number;
  processed_at: number;
  detections: CameraVisionDetection[];
  metadata: CameraVisionMetadata;
}

export async function getCameras(): Promise<CameraDto[]> {
  const response = await apiClient<{ items: CameraDto[]; total: number }>("/cameras");
  return response.items;
}

export function getCamera(id: string): Promise<CameraDto> {
  return apiClient(`/cameras/${encodeURIComponent(id)}`);
}

export function getLatestCameraVision(
  id: string,
  signal?: AbortSignal,
): Promise<{ result: CameraVisionResult | null }> {
  return apiClient(`/cameras/${encodeURIComponent(id)}/vision/latest`, { signal });
}

export function updateCameraSource(
  id: string,
  source: Pick<CameraDto, "source_kind"> & { source_uri?: string; playback_path?: string },
): Promise<CameraDto> {
  return apiClient(`/cameras/${encodeURIComponent(id)}/source`, {
    method: "PATCH",
    body: JSON.stringify(source),
  });
}

export function updateCamera(
  id: string,
  data: { name:string; location:string; source_kind:CameraDto["source_kind"]; source_uri?:string; playback_path?:string },
): Promise<CameraDto> {
  return apiClient(`/cameras/${encodeURIComponent(id)}`, { method:"PATCH", body:JSON.stringify(data) });
}

export function deleteCamera(id:string): Promise<void> {
  return apiCommand(`/cameras/${encodeURIComponent(id)}`, { method:"DELETE" });
}

export function setCameraEnabled(id: string, enabled: boolean): Promise<unknown> {
  return apiClient(`/cameras/${encodeURIComponent(id)}/${enabled ? "start" : "stop"}`, { method: "POST" });
}

export function setCameraVision(id: string, enabled: boolean): Promise<unknown> {
  return apiClient(`/cameras/${encodeURIComponent(id)}/vision/${enabled ? "enable" : "disable"}`, { method: "POST" });
}
