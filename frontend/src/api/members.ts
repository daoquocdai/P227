import { apiClient } from "./client";
import type { Member, PaginatedResponse } from "../types";

export function getMembers(): Promise<PaginatedResponse<Member>> {
  return apiClient("/members");
}

