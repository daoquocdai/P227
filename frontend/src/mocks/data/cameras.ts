import type { Camera } from "../../types";
export const mockCameras: Camera[] = [
  { id: "cam-bedroom", name: "Camera phòng ngủ", zoneId: "bedroom", zoneName: "Phòng ngủ", status: "online", sourceType: "webcam" },
  { id: "cam-living", name: "Camera phòng khách", zoneId: "living", zoneName: "Phòng khách", status: "online", sourceType: "mp4" },
];

