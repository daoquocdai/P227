import { apiClient } from "./client";
import type { Camera, PaginatedResponse } from "../types";

export function getCameras(): Promise<PaginatedResponse<Camera>> {
  return apiClient("/cameras");
}

