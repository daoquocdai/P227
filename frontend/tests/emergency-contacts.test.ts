import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { AuthUser } from "../src/api/auth.ts";
import type { EmergencyContact } from "../src/api/emergencyContacts.ts";
import {
  canManageEmergencyContacts,
  changedContactFields,
  emergencyContactError,
  isLastActiveContact,
  isValidE164,
  nextContactPriority,
  normalizeVietnamPhone,
  replaceContact,
  sortEmergencyContacts,
} from "../src/features/emergencyContacts/contactModel.ts";

const apiSource = readFileSync(new URL("../src/api/emergencyContacts.ts", import.meta.url), "utf8");
const panelSource = readFileSync(
  new URL("../src/features/emergencyContacts/EmergencyContactsPanel.tsx", import.meta.url),
  "utf8",
);
const settingsSource = readFileSync(new URL("../src/pages/SettingsPage.tsx", import.meta.url), "utf8");

function contact(overrides: Partial<EmergencyContact> = {}): EmergencyContact {
  return {
    id: "contact-1",
    display_name: "Nguyễn Văn An",
    relationship_label: "Con trai",
    phone_e164: "+84912345678",
    priority: 1,
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function user(overrides: Partial<AuthUser> = {}): AuthUser {
  return {
    id: "user-1",
    email: "caregiver@example.com",
    name: "Caregiver",
    role: "caregiver",
    force_password_change: false,
    permissions: {
      view_history: false,
      acknowledge_alert: false,
      resolve_alert: false,
      manage_cameras: false,
      manage_persons: false,
      manage_users: false,
    },
    ...overrides,
  };
}

test("list sorts contacts by priority and stable creation order", () => {
  const sorted = sortEmergencyContacts([
    contact({ id: "later", priority: 2 }),
    contact({ id: "same-later", created_at: "2026-01-02T00:00:00Z" }),
    contact({ id: "first" }),
  ]);
  assert.deepEqual(sorted.map(({ id }) => id), ["first", "same-later", "later"]);
  assert.match(panelSource, /display_name/);
  assert.match(panelSource, /relationship_label/);
  assert.match(panelSource, /phone_e164/);
});

test("empty state tells the user how to add the first contact", () => {
  assert.match(panelSource, /Chưa có liên hệ khẩn cấp/);
  assert.match(panelSource, /Thêm ít nhất một số/);
});

test("create uses POST on the emergency contacts collection", () => {
  assert.match(apiSource, /apiClient\("\/emergency-contacts", \{ method: "POST"/);
  assert.match(panelSource, /sortEmergencyContacts\(\[\.\.\.current, saved\]\)/);
});

test("Vietnamese local phone is normalized to E.164", () => {
  assert.equal(normalizeVietnamPhone("0912 345-678"), "+84912345678");
});

test("existing international E.164 phone is preserved", () => {
  assert.equal(normalizeVietnamPhone(" +84912345678 "), "+84912345678");
});

test("invalid phone is rejected before submission", () => {
  assert.equal(isValidE164("0912345678"), false);
  assert.equal(isValidE164("+840912345678"), true);
  assert.equal(isValidE164("+84abc"), false);
  assert.match(panelSource, /if \(!isValidE164\(phone\)\)/);
});

test("new priority defaults to max plus one and remains in backend bounds", () => {
  assert.equal(nextContactPriority([]), 1);
  assert.equal(nextContactPriority([contact({ priority: 8 })]), 9);
  assert.equal(nextContactPriority([contact({ priority: 1000 })]), 1000);
  assert.match(panelSource, /priority: draft\.priority/);
});

test("edit payload contains only changed fields", () => {
  const original = contact();
  assert.deepEqual(changedContactFields(original, {
    display_name: original.display_name,
    phone_e164: original.phone_e164,
    priority: 2,
  }), { priority: 2 });
  assert.match(apiSource, /method: "PATCH"/);
});

test("deactivate uses DELETE without removing the row", () => {
  assert.match(apiSource, /method: "DELETE"/);
  const inactive = contact({ is_active: false, updated_at: "2026-02-01T00:00:00Z" });
  assert.deepEqual(replaceContact([contact()], inactive), [inactive]);
});

test("inactive contacts remain visibly labelled", () => {
  assert.match(panelSource, /Đã tắt/);
  assert.match(panelSource, /contact\.is_active \? "" : "inactive"/);
});

test("reactivation patches is_active true", () => {
  assert.match(panelSource, /updateEmergencyContact\(contact\.id, \{ is_active: true \}\)/);
  assert.match(panelSource, /Kích hoạt lại/);
});

test("deactivating the last active contact triggers explicit warning", () => {
  const selected = contact();
  assert.equal(isLastActiveContact([selected, contact({ id: "off", is_active: false })], selected), true);
  assert.match(panelSource, /liên hệ khẩn cấp đang hoạt động cuối cùng/);
});

test("last-active warning is absent when another active contact exists", () => {
  const selected = contact();
  assert.equal(isLastActiveContact([selected, contact({ id: "active-2" })], selected), false);
});

test("403 permission failure has a dedicated Vietnamese message", () => {
  assert.equal(
    emergencyContactError(new Error("Không có quyền quản lý liên hệ khẩn cấp")),
    "Bạn không có quyền quản lý liên hệ khẩn cấp.",
  );
});

test("mutation failure message states that current list is retained", () => {
  assert.match(emergencyContactError(new Error("boom"), "save"), /vẫn được giữ nguyên/);
  assert.match(panelSource, /catch \(mutationError\)/);
});

test("saving guard prevents duplicate mutation submissions", () => {
  assert.match(panelSource, /if \(savingRef\.current \|\| editing === null\) return/);
  assert.match(panelSource, /if \(!confirming \|\| savingRef\.current\) return/);
  assert.match(panelSource, /disabled=\{saving\}/);
});

test("admin and manage_persons caregiver can manage contacts", () => {
  assert.equal(canManageEmergencyContacts(user({ role: "admin" })), true);
  assert.equal(canManageEmergencyContacts(user({ permissions: { ...user().permissions, manage_persons: true } })), true);
});

test("unauthorized caregiver cannot see the emergency contact tab", () => {
  assert.equal(canManageEmergencyContacts(user()), false);
  assert.match(settingsSource, /id!=="emergency_contacts"\|\|canManageContacts/);
  assert.match(settingsSource, /tab==="emergency_contacts"&&canManageContacts/);
});

test("component loads contacts once without polling", () => {
  assert.equal((panelSource.match(/getEmergencyContacts\(\)/g) ?? []).length, 1);
  assert.doesNotMatch(panelSource, /setInterval|setTimeout/);
});

test("modal supports Escape, focus, labels, and dialog semantics", () => {
  assert.match(panelSource, /event\.key !== "Escape"/);
  assert.match(panelSource, /firstInputRef\.current\?\.focus/);
  assert.match(panelSource, /role="dialog"/);
  assert.match(panelSource, /role="alertdialog"/);
  assert.match(panelSource, /htmlFor="contact-phone"/);
});
