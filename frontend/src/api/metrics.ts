import { apiClient } from "./client";

export type StatisticsPeriod = "today" | "7d" | "30d" | "custom";
export type TrendMetric = {
  value: number | null;
  change_percent: number | null;
  improved: boolean | null;
};
export type CameraMetric = {
  id: string;
  name: string;
  location_label: string | null;
  measured_at: string | null;
  source_kind: "video_file" | "webcam" | "rtsp" | null;
  is_active: boolean;
  camera_status: "disabled" | "waiting" | "online" | "disconnected" | "error" | "ended" | null;
  historical_sample_at: string | null;
  data_source: "runtime" | "persisted" | "none";
  is_stale: boolean;
  last_seen_at: string | null;
  raw_fps: number | null;
  vision_status: "disabled" | "error" | "running" | "waiting_for_source" | null;
  vision_fps: number | null;
  vision_processing_latency_ms: number | null;
  vision_drop_ratio: number | null;
  pending: number | null;
  max_pending: number | null;
  vision_frames_offered: number | null;
  vision_frames_overwritten: number | null;
};
export type StatisticsData = {
  range: { start: string; end: string; timezone: string };
  kpis: Record<"total_alerts" | "true_alerts" | "false_alerts" | "unconfirmed_alerts" | "false_alarm_rate" | "average_response_ms", TrendMetric>;
  alert_bucket: { unit: "hour" | "day"; timezone: string };
  alert_timeline: Array<{ bucket_start: string; alert_type: "fall" | "unknown_person"; total: number; confirmed: number; false_alarms: number }>;
  camera_distribution: Array<{ id: string; name: string; location: string | null; alert_count: number; false_alarm_rate: number | null }>;
  false_alarm_reasons: Array<{ note: string; count: number }>;
  hub_metrics: null | { measured_at: string; process_cpu_percent: number | null; process_rss_mb: number | null; host_memory_total_mb: number | null; host_memory_used_percent: number | null; disk_used_percent: number | null; data_source: "persisted"; is_stale: boolean };
  camera_metrics: CameraMetric[];
  performance_timeline: Array<{ camera_id: string; measured_at: string; camera_name: string; raw_fps: number | null; vision_fps: number | null; vision_processing_latency_ms: number | null; vision_drop_ratio: number | null; max_pending: number | null; sample_count: number; bucket_seconds: number }>;
  performance_series: Array<{ camera_id: string; camera_name: string; sample_count: number; bucket_count: number; bucket_seconds: number }>;
  threshold_alerts: Array<{ scope: "hub" | "camera"; id: string; name: string; reasons: string[] }>;
};

function localBoundary(date: string, nextDay: boolean) {
  const value = new Date(`${date}T00:00:00+07:00`);
  if (nextDay) value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString();
}

export function getStatistics(period: StatisticsPeriod, start?: string, end?: string) {
  const query = new URLSearchParams({ period });
  if (period === "custom" && start && end) {
    query.set("start", localBoundary(start, false));
    query.set("end", localBoundary(end, true));
  }
  return apiClient<StatisticsData>(`/statistics?${query}`);
}
