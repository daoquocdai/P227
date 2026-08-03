import { http, HttpResponse } from "msw";

import { mockCameras } from "./data/cameras";
import { mockEvents } from "./data/events";
import { mockMembers } from "./data/members";
import { mockMetrics } from "./data/metrics";

const page = <T>(items: T[]) => ({
  items,
  page: 1,
  page_size: 20,
  total: items.length,
});

export const handlers = [
  http.get("*/api/v1/events", () => HttpResponse.json(page(mockEvents))),
  http.get("*/api/v1/events/:id", ({ params }) => {
    const event = mockEvents.find((item) => item.id === params.id);
    return event
      ? HttpResponse.json(event)
      : HttpResponse.json({ error: { code: "EVENT_NOT_FOUND" } }, { status: 404 });
  }),
  http.post("*/api/v1/events/:id/reviews", async ({ params, request }) => {
    const event = mockEvents.find((item) => item.id === params.id);
    if (!event) return HttpResponse.json({}, { status: 404 });
    const body = (await request.json()) as { status: typeof event.status };
    return HttpResponse.json({ ...event, status: body.status });
  }),
  http.get("*/api/v1/cameras", () => HttpResponse.json(page(mockCameras))),
  http.get("*/api/v1/members", () => HttpResponse.json(page(mockMembers))),
  http.get("*/api/v1/metrics", () => HttpResponse.json(mockMetrics)),
];

