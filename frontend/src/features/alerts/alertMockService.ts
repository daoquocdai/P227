import { initialAlerts } from "./alertMockData";
import type { AlertEvent } from "./alert.types";

export async function fetchAlerts(): Promise<AlertEvent[]> {
  await new Promise((resolve) => window.setTimeout(resolve, 550));
  return initialAlerts.map((alert) => ({ ...alert }));
}

