export type AlertType = "fall" | "inactivity" | "stranger" | "camera" | "arrival";
export type AlertSeverity = "info" | "medium" | "high" | "critical";
export type AlertStatus = "pending" | "checking" | "resolved" | "safe" | "false_alarm" | "need_help";
export type ChatRole = "assistant" | "user";
export type MessageContentType = "text" | "event" | "snapshot" | "camera" | "confidence" | "success" | "help" | "false_alarm";

export interface AlertEvent {
  id: string;
  cameraId: string;
  eventId: string;
  occurredAt: string;
  type: AlertType;
  title: string;
  subject: string;
  location: string;
  time: string;
  timestamp: string;
  severity: AlertSeverity;
  status: AlertStatus;
  unread: boolean;
  preview: string;
  confidence?: number;
  immobileSeconds?: number;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  contentType: MessageContentType;
  createdAt: string;
}

export interface QuickAction {
  id: "camera" | "safe" | "help" | "why" | "false_alarm" | "snapshot";
  label: string;
}

export type AlertFilter = "all" | "pending" | "critical" | "resolved";
