import type { SystemMetrics } from "../../types";
export const mockMetrics: SystemMetrics = {
  personDetection: { precision: .94, recall: .92, falsePositiveRate: .03 },
  fallDetection: { precision: .91, recall: .89, falsePositiveRate: .05 },
  performance: { fps: 24, averageLatencyMs: 86, p95LatencyMs: 140, modelSizeMb: 32 }, isMock: true,
};
