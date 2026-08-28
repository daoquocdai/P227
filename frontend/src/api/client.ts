export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

let authToken = localStorage.getItem("antam_token") ?? sessionStorage.getItem("antam_token");

export function getAuthToken(): string | null {
  return authToken;
}

export function setAuthToken(token: string | null, remember: boolean) {
  authToken = token;
  localStorage.removeItem("antam_token");
  sessionStorage.removeItem("antam_token");
  if (token) (remember ? localStorage : sessionStorage).setItem("antam_token", token);
}

async function apiResponse(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `API request failed with status ${response.status}`);
  }

  return response;
}

export async function apiClient<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiResponse(path, init);
  if (response.status === 204) {
    throw new Error("API returned no content for a JSON request");
  }

  return response.json() as Promise<T>;
}

export async function apiCommand(path: string, init?: RequestInit): Promise<void> {
  const response = await apiResponse(path, init);
  if (response.status !== 204) {
    throw new Error(`API command expected status 204 but received ${response.status}`);
  }
}

