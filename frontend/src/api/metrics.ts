import { apiClient } from "./client";
import type { SystemMetrics } from "../types";

export function getMetrics(): Promise<SystemMetrics> {
  return apiClient("/metrics");
}

