import { apiClient } from "./client";
import type { PaginatedResponse, SecurityEvent } from "../types";

export function getEvents(): Promise<PaginatedResponse<SecurityEvent>> {
  return apiClient("/events");
}

export function getEvent(id: string): Promise<SecurityEvent> {
  return apiClient(`/events/${id}`);
}

export function reviewEvent(
  id: string,
  status: SecurityEvent["status"],
  note?: string,
): Promise<SecurityEvent> {
  return apiClient(`/events/${id}/reviews`, {
    method: "POST",
    body: JSON.stringify({ status, note }),
  });
}

