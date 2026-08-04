import type { AlertRecipient, EmergencyContact } from "./cameraDetail.types";

// Contact actions remain baseline-only until the users/notification backend is connected.
export const emergencyContact: EmergencyContact = {
  id: "contact-minh",
  name: "Minh Nguyễn",
  relationship: "Người chăm sóc",
  maskedPhone: "09•• ••• 128",
};

export const alertRecipients: AlertRecipient[] = [
  { id: "minh", name: "Minh Nguyễn", role: "Người chăm sóc chính", enabled: true },
  { id: "hong", name: "Hồng Anh", role: "Người thân", enabled: true },
  { id: "neighbor", name: "Hàng xóm hỗ trợ", role: "Liên hệ dự phòng", enabled: false },
];
