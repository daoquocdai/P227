import type { AuthUser } from "../../api/auth";
import type { EmergencyContact, EmergencyContactUpdate } from "../../api/emergencyContacts";

export function canManageEmergencyContacts(user: AuthUser): boolean {
  return user.role === "admin" || user.permissions.manage_persons === true;
}

export function normalizeVietnamPhone(value: string): string {
  const compact = value.trim().replace(/[\s-]/g, "");
  if (/^0\d+$/.test(compact)) return `+84${compact.slice(1)}`;
  return compact;
}

export function isValidE164(value: string): boolean {
  return /^\+[1-9]\d{7,14}$/.test(value);
}

export function sortEmergencyContacts(contacts: EmergencyContact[]): EmergencyContact[] {
  return [...contacts].sort((left, right) =>
    left.priority - right.priority
    || left.created_at.localeCompare(right.created_at)
    || left.id.localeCompare(right.id));
}

export function nextContactPriority(contacts: EmergencyContact[]): number {
  return contacts.length ? Math.min(1000, Math.max(...contacts.map((contact) => contact.priority)) + 1) : 1;
}

export function isLastActiveContact(contacts: EmergencyContact[], selected: EmergencyContact): boolean {
  return selected.is_active && contacts.filter((contact) => contact.is_active).length === 1;
}

export function replaceContact(contacts: EmergencyContact[], updated: EmergencyContact): EmergencyContact[] {
  return sortEmergencyContacts(contacts.map((contact) => contact.id === updated.id ? updated : contact));
}

export function changedContactFields(
  original: EmergencyContact,
  next: EmergencyContactUpdate,
): EmergencyContactUpdate {
  return Object.fromEntries(
    Object.entries(next).filter(([key, value]) => original[key as keyof EmergencyContact] !== value),
  ) as EmergencyContactUpdate;
}

export function emergencyContactError(error: unknown, action = "load"): string {
  const message = error instanceof Error ? error.message : "";
  if (message.includes("Không có quyền") || message.includes("403")) {
    return "Bạn không có quyền quản lý liên hệ khẩn cấp.";
  }
  if (message.includes("E.164") || message.includes("phone_e164")) {
    return "Số điện thoại chưa đúng. Hãy nhập dạng 0912345678 hoặc +84912345678.";
  }
  if (/Failed to fetch|NetworkError|fetch failed/i.test(message)) {
    return "Không kết nối được Local Hub.";
  }
  return action === "load"
    ? "Không tải được danh sách liên hệ khẩn cấp."
    : "Không lưu được thay đổi. Danh sách hiện tại vẫn được giữ nguyên.";
}
