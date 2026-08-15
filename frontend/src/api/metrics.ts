import { apiClient } from "./client";

export type TrendMetric = { value: number; change_percent: number | null; improved: boolean | null };
export type StatisticsPeriod = "today" | "7d" | "30d" | "custom";
export interface StatisticsData {
  range: { start: string; end: string };
  kpis: Record<"total_alerts" | "true_alerts" | "false_alerts" | "unconfirmed_alerts" | "false_alarm_rate" | "average_response_ms", TrendMetric>;
  alert_timeline: Array<{ day: string; alert_type: "fall" | "unknown_person"; total: number; confirmed: number; false_alarms: number }>;
  camera_distribution: Array<{ id: string; name: string; location: string; alert_count: number; false_alarm_rate: number }>;
  false_alarm_reasons: Array<{ note: string; count: number }>;
  devices: Array<{ id: string; name: string; location_label: string; operational_status: "online" | "offline" | "error"; last_seen_at: string | null; fps: number | null; latency_ms: number | null; inference_measured_at: string | null; ram_usage_mb: number | null; ram_total_mb: number | null; cpu_usage_percent: number | null; ping_ms: number | null; disk_usage_percent: number | null; device_measured_at: string | null }>;
  performance_timeline: Array<{ measured_at: string; camera_name: string; fps: number | null; latency_ms: number | null }>;
  threshold_alerts: Array<{ camera_id: string; camera_name: string; reasons: string[] }>;
}

export function getStatistics(period: StatisticsPeriod, start?: string, end?: string): Promise<StatisticsData> {
  const query = new URLSearchParams({ period });
  if (start) query.set("start", new Date(start).toISOString());
  if (end) query.set("end", new Date(`${end}T23:59:59`).toISOString());
  return apiClient(`/statistics?${query}`);
}

