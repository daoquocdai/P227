export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

async function apiResponse(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`API request failed with status ${response.status}`);
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

