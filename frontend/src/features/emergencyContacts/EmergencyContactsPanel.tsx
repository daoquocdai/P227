import { ContactRound, LoaderCircle, Pencil, PhoneCall, Plus, Power, RotateCcw, ShieldAlert, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  createEmergencyContact,
  deactivateEmergencyContact,
  getEmergencyContacts,
  updateEmergencyContact,
  type EmergencyContact,
  type EmergencyContactCreate,
} from "../../api/emergencyContacts";
import {
  changedContactFields,
  emergencyContactError,
  isLastActiveContact,
  isValidE164,
  nextContactPriority,
  normalizeVietnamPhone,
  replaceContact,
  sortEmergencyContacts,
} from "./contactModel";

type ContactDraft = EmergencyContactCreate;

const emptyDraft = (priority: number): ContactDraft => ({
  display_name: "",
  relationship_label: null,
  phone_e164: "",
  priority,
  is_active: true,
});

export function EmergencyContactsPanel() {
  const [contacts, setContacts] = useState<EmergencyContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<EmergencyContact | "new" | null>(null);
  const [draft, setDraft] = useState<ContactDraft>(emptyDraft(1));
  const [confirming, setConfirming] = useState<EmergencyContact | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const savingRef = useRef(false);
  const firstInputRef = useRef<HTMLInputElement>(null);
  const addButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    void getEmergencyContacts()
      .then((items) => {
        if (mounted) setContacts(sortEmergencyContacts(items));
      })
      .catch((loadError) => {
        if (mounted) setError(emergencyContactError(loadError));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    if (!editing && !confirming) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || savingRef.current) return;
      setEditing(null);
      setConfirming(null);
      addButtonRef.current?.focus();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [editing, confirming]);

  useEffect(() => {
    if (editing) window.requestAnimationFrame(() => firstInputRef.current?.focus());
  }, [editing]);

  const openCreate = () => {
    setDraft(emptyDraft(nextContactPriority(contacts)));
    setFormError("");
    setEditing("new");
  };

  const openEdit = (contact: EmergencyContact) => {
    setDraft({
      display_name: contact.display_name,
      relationship_label: contact.relationship_label,
      phone_e164: contact.phone_e164,
      priority: contact.priority,
      is_active: contact.is_active,
    });
    setFormError("");
    setEditing(contact);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (savingRef.current || editing === null) return;
    const phone = normalizeVietnamPhone(draft.phone_e164);
    const displayName = draft.display_name.trim();
    if (!displayName) {
      setFormError("Hãy nhập tên liên hệ.");
      return;
    }
    if (!isValidE164(phone)) {
      setFormError("Số điện thoại chưa đúng. Hãy nhập dạng 0912345678 hoặc +84912345678.");
      return;
    }
    if (!Number.isInteger(draft.priority) || draft.priority < 1 || draft.priority > 1000) {
      setFormError("Ưu tiên phải là số nguyên từ 1 đến 1000.");
      return;
    }

    const payload: ContactDraft = {
      display_name: displayName,
      relationship_label: draft.relationship_label?.trim() || null,
      phone_e164: phone,
      priority: draft.priority,
      is_active: draft.is_active,
    };
    savingRef.current = true;
    setSaving(true);
    setFormError("");
    try {
      const saved = editing === "new"
        ? await createEmergencyContact(payload)
        : await updateEmergencyContact(editing.id, changedContactFields(editing, payload));
      setContacts((current) => editing === "new"
        ? sortEmergencyContacts([...current, saved])
        : replaceContact(current, saved));
      setEditing(null);
      setError("");
      addButtonRef.current?.focus();
    } catch (mutationError) {
      setFormError(emergencyContactError(mutationError, "save"));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  const deactivate = async () => {
    if (!confirming || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      const updated = await deactivateEmergencyContact(confirming.id);
      setContacts((current) => replaceContact(current, updated));
      setConfirming(null);
      setError("");
    } catch (mutationError) {
      setError(emergencyContactError(mutationError, "save"));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  const reactivate = async (contact: EmergencyContact) => {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      const updated = await updateEmergencyContact(contact.id, { is_active: true });
      setContacts((current) => replaceContact(current, updated));
      setError("");
    } catch (mutationError) {
      setError(emergencyContactError(mutationError, "save"));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  return <div className="settings-scroll-content emergency-contact-settings">
    <header className="section-page-heading"><div><h2>Liên hệ khẩn cấp</h2><p>Quản lý người được gọi khi có sự cố té ngã chưa xác nhận an toàn.</p></div><button ref={addButtonRef} className="settings-primary-small" disabled={saving} onClick={openCreate}><Plus/> Thêm liên hệ</button></header>

    {error && <div className="contact-inline-error" role="alert"><ShieldAlert/><span>{error}</span><button aria-label="Đóng thông báo lỗi" onClick={() => setError("")}><X/></button></div>}

    <section className="settings-section-card emergency-context-card"><span><PhoneCall/></span><div><strong>Cách Local Hub liên hệ</strong><p>Khi phát hiện té ngã và chưa có xác nhận an toàn, Local Hub sẽ liên hệ các số đang hoạt động theo thứ tự ưu tiên, sau thời gian chờ đã cấu hình.</p><small>Cuộc gọi thật yêu cầu Emergency Call Provider được cấu hình trên Local Hub.</small></div></section>

    <section className="settings-section-card contact-list-card">
      <header><div><h3>Danh sách liên hệ</h3><p>Số có ưu tiên 1 sẽ được liên hệ trước. Các liên hệ cùng mức giữ thứ tự tạo.</p></div><span>{contacts.filter((contact) => contact.is_active).length} đang hoạt động</span></header>
      {loading ? <div className="contact-state"><LoaderCircle className="contact-spinner"/><strong>Đang tải liên hệ…</strong></div>
        : contacts.length === 0 ? <div className="contact-state"><ContactRound/><strong>Chưa có liên hệ khẩn cấp</strong><p>Thêm ít nhất một số để hệ thống có thể liên hệ khi cần.</p></div>
          : <div className="emergency-contact-list" role="table" aria-label="Danh sách liên hệ khẩn cấp">
            <div className="emergency-contact-head" role="row"><span>Tên / Quan hệ</span><span>Số điện thoại</span><span>Ưu tiên</span><span>Trạng thái</span><span>Hành động</span></div>
            {contacts.map((contact) => <div className={`emergency-contact-row ${contact.is_active ? "" : "inactive"}`} role="row" key={contact.id}>
              <div><span className="contact-priority-number">{contact.priority}</span><span><strong>{contact.display_name}</strong><small>{contact.relationship_label || "Chưa ghi quan hệ"}</small></span></div>
              <a href={`tel:${contact.phone_e164}`}>{contact.phone_e164}</a>
              <span>Ưu tiên {contact.priority}</span>
              <span className={`contact-status ${contact.is_active ? "active" : "inactive"}`}>{contact.is_active ? "Đang hoạt động" : "Đã tắt"}</span>
              <div className="contact-actions"><button disabled={saving} onClick={() => openEdit(contact)}><Pencil/> Sửa</button>{contact.is_active
                ? <button className="contact-disable" disabled={saving} onClick={() => setConfirming(contact)}><Power/> Tắt liên hệ</button>
                : <button disabled={saving} onClick={() => void reactivate(contact)}><RotateCcw/> Kích hoạt lại</button>}</div>
            </div>)}
          </div>}
    </section>

    {editing && <div className="settings-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && !saving && setEditing(null)}><form className="settings-modal emergency-contact-modal" role="dialog" aria-modal="true" aria-labelledby="contact-form-title" onSubmit={submit}><header><div><h3 id="contact-form-title">{editing === "new" ? "Thêm liên hệ khẩn cấp" : "Sửa liên hệ khẩn cấp"}</h3><p>Thông tin này được lưu cục bộ trên Local Hub.</p></div><button type="button" disabled={saving} aria-label="Đóng biểu mẫu" onClick={() => setEditing(null)}><X/></button></header>
      {formError && <p className="contact-form-error" role="alert">{formError}</p>}
      <label htmlFor="contact-display-name"><span>Tên liên hệ *</span><input ref={firstInputRef} id="contact-display-name" value={draft.display_name} maxLength={255} required onChange={(event) => setDraft({...draft, display_name:event.target.value})}/></label>
      <label htmlFor="contact-relationship"><span>Quan hệ</span><input id="contact-relationship" list="relationship-options" value={draft.relationship_label ?? ""} maxLength={100} placeholder="Ví dụ: Con trai" onChange={(event) => setDraft({...draft, relationship_label:event.target.value})}/><datalist id="relationship-options"><option value="Con trai"/><option value="Con gái"/><option value="Vợ"/><option value="Chồng"/><option value="Anh/chị/em"/><option value="Người chăm sóc"/></datalist></label>
      <label htmlFor="contact-phone"><span>Số điện thoại *</span><input id="contact-phone" type="tel" inputMode="tel" value={draft.phone_e164} required placeholder="0912345678" aria-describedby="contact-phone-help" onChange={(event) => setDraft({...draft, phone_e164:event.target.value})}/><small id="contact-phone-help">Ví dụ: 0912345678 hoặc +84912345678</small></label>
      <label htmlFor="contact-priority"><span>Ưu tiên *</span><input id="contact-priority" type="number" min="1" max="1000" step="1" value={draft.priority} required onChange={(event) => setDraft({...draft, priority:Number(event.target.value)})}/><small>Số nhỏ hơn sẽ được gọi trước.</small></label>
      <label className="contact-active-field"><input type="checkbox" checked={draft.is_active} onChange={(event) => setDraft({...draft, is_active:event.target.checked})}/><span>Đang hoạt động</span></label>
      <footer><button type="button" disabled={saving} onClick={() => setEditing(null)}>Hủy</button><button type="submit" disabled={saving}>{saving ? "Đang lưu…" : editing === "new" ? "Thêm liên hệ" : "Lưu thay đổi"}</button></footer>
    </form></div>}

    {confirming && <div className="settings-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && !saving && setConfirming(null)}><section className="settings-modal contact-confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="contact-confirm-title"><header><div><h3 id="contact-confirm-title">Tắt liên hệ khẩn cấp này?</h3><p>Hệ thống sẽ không gọi số {confirming.phone_e164} khi có sự cố.</p></div><button disabled={saving} aria-label="Đóng xác nhận" onClick={() => setConfirming(null)}><X/></button></header>
      {isLastActiveContact(contacts, confirming) && <div className="last-active-warning"><ShieldAlert/><p><strong>Đây là liên hệ khẩn cấp đang hoạt động cuối cùng.</strong><span>Nếu tắt, hệ thống sẽ không có số điện thoại để gọi khi phát hiện té ngã.</span></p></div>}
      <footer><button disabled={saving} onClick={() => setConfirming(null)}>Giữ liên hệ</button><button className="confirm-contact-disable" disabled={saving} onClick={() => void deactivate()}>{saving ? "Đang tắt…" : "Tắt liên hệ"}</button></footer>
    </section></div>}
  </div>;
}
