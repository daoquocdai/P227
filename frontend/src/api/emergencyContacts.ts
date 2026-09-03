import { apiClient } from "./client";

export interface EmergencyContact {
  id: string;
  display_name: string;
  relationship_label: string | null;
  phone_e164: string;
  priority: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface EmergencyContactCreate {
  display_name: string;
  relationship_label?: string | null;
  phone_e164: string;
  priority: number;
  is_active: boolean;
}

export type EmergencyContactUpdate = Partial<EmergencyContactCreate>;

export async function getEmergencyContacts(): Promise<EmergencyContact[]> {
  const response = await apiClient<{ items: EmergencyContact[] }>("/emergency-contacts");
  return response.items;
}

export function createEmergencyContact(data: EmergencyContactCreate): Promise<EmergencyContact> {
  return apiClient("/emergency-contacts", { method: "POST", body: JSON.stringify(data) });
}

export function updateEmergencyContact(
  id: string,
  data: EmergencyContactUpdate,
): Promise<EmergencyContact> {
  return apiClient(`/emergency-contacts/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function deactivateEmergencyContact(id: string): Promise<EmergencyContact> {
  return apiClient(`/emergency-contacts/${encodeURIComponent(id)}`, { method: "DELETE" });
}
