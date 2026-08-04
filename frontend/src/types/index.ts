export type IdentityStatus = "recognized" | "unknown" | "uncertain" | "not_available";
export type EventType =
  | "person_detected"
  | "unknown_person"
  | "possible_intrusion"
  | "possible_fall"
  | "fall_with_immobility";
export type Severity = "info" | "warning" | "high" | "critical";
export type EventStatus =
  | "pending_review"
  | "confirmed"
  | "false_alarm"
  | "needs_attention"
  | "resolved";

export interface Camera {
  id: string;
  name: string;
  zoneId: string;
  zoneName: string;
  status: "online" | "offline";
  sourceType: "mp4" | "webcam";
  previewUrl?: string;
  lastSeenAt?: string;
}

export interface Member {
  id: string;
  name: string;
  relationship: string;
  avatarUrl?: string;
  lastSeenAt?: string;
  lastSeenZone?: string;
}

export interface SecurityEvent {
  id: string;
  cameraId: string;
  cameraName: string;
  zoneId: string;
  zoneName: string;
  eventType: EventType;
  severity: Severity;
  status: EventStatus;
  occurredAt: string;
  endedAt?: string | null;
  description: string;
  identity: {
    memberId: string | null;
    memberName: string | null;
    status: IdentityStatus;
    confidence: number | null;
  };
  fall?: {
    confidence: number;
    immobileSeconds: number;
  } | null;
  snapshotUrl?: string | null;
}

export interface SystemMetrics {
  personDetection: { precision: number; recall: number; falsePositiveRate: number };
  fallDetection: { precision: number; recall: number; falsePositiveRate: number };
  performance: {
    fps: number;
    averageLatencyMs: number;
    p95LatencyMs: number;
    modelSizeMb: number;
  };
  isMock: boolean;
}

export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}

