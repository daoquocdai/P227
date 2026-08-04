import { apiClient } from "./client";

export interface FaceProfileDto {
  id: string;
  quality: number;
  angle: string;
  model: string;
  active: boolean;
}

export interface PersonDto {
  id: string;
  name: string;
  relationship: string;
  birth?: string | null;
  notes?: string | null;
  active: boolean;
  faces: FaceProfileDto[];
}

export async function getPeople(): Promise<PersonDto[]> {
  return (await apiClient<{ items: PersonDto[] }>("/persons")).items;
}

export function createPerson(data: Omit<PersonDto, "id" | "faces">): Promise<PersonDto> {
  return apiClient("/persons", { method: "POST", body: JSON.stringify(data) });
}

export function updatePerson(id: string, data: Partial<Omit<PersonDto, "id" | "faces">>): Promise<PersonDto> {
  return apiClient(`/persons/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(data) });
}

export function addFace(id: string, quality: number, angle = "Ảnh mới"): Promise<PersonDto> {
  return apiClient(`/persons/${encodeURIComponent(id)}/faces`, {
    method: "POST", body: JSON.stringify({ quality, angle }),
  });
}

export function deleteFace(id: string, faceId: string): Promise<PersonDto> {
  return apiClient(`/persons/${encodeURIComponent(id)}/faces/${encodeURIComponent(faceId)}`, { method: "DELETE" });
}
