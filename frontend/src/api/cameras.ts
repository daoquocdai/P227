import { apiClient } from "./client";

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
  status: "online" | "offline" | "error";
  last_seen_at?: string | null;
  active: boolean;
  source_kind: "video_file" | "webcam" | "rtsp";
  playback_url?: string | null;
  stream_ready: boolean;
  events?: CameraEventDto[];
}

export async function getCameras(): Promise<CameraDto[]> {
  const response = await apiClient<{ items: CameraDto[]; total: number }>("/cameras");
  return response.items;
}

export function getCamera(id: string): Promise<CameraDto> {
  return apiClient(`/cameras/${encodeURIComponent(id)}`);
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
