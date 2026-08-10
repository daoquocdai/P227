import { AlertTriangle, Camera, Check, Image, Plus, RefreshCw, Search, ShieldCheck, Trash2, UsersRound, X } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { addFace, createPerson, deleteFace, getPeople, updatePerson, type PersonDto } from "../api/persons";
import "./family.css";

type Person = PersonDto & { color: string };
const colors = ["blue", "teal", "violet", "orange", "pink"];
const toPerson = (person: PersonDto): Person => ({ ...person, color: colors[person.id.charCodeAt(0) % colors.length] });
const normalize = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d").toLowerCase();
const averageQuality = (person: Person) => person.faces.length ? person.faces.reduce((sum, face) => sum + face.quality, 0) / person.faces.length : 0;
const qualityInfo = (score: number, count: number) => count === 0 || score < .5
  ? { tone: "poor", label: "Chưa đủ dữ liệu" }
  : score <= .8 ? { tone: "fair", label: "Cần cải thiện" } : { tone: "good", label: "Nhận diện tốt" };

function PersonAvatar({ person, large = false }: { person: Person; large?: boolean }) {
  const initials = person.name.split(" ").map((part) => part[0]).slice(-2).join("");
  return <span className={`family-avatar ${person.color} ${large ? "large" : ""}`}><span>{initials}</span>{person.faces.length > 0 && <i><Camera /></i>}</span>;
}

export default function FamilyPage() {
  const [people, setPeople] = useState<Person[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState("");
  const [showHidden, setShowHidden] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [faceFlow, setFaceFlow] = useState(false);
  const [faceQuality, setFaceQuality] = useState<number | null>(null);

  const load = () => {
    setLoading(true); setError(false);
    getPeople().then((items) => setPeople(items.map(toPerson))).catch(() => setError(true)).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const selected = people.find((person) => person.id === selectedId) ?? null;
  const visible = useMemo(() => people.filter((person) => {
    const matchesVisibility = showHidden || person.active;
    const text = normalize(`${person.name} ${person.relationship}`);
    return matchesVisibility && text.includes(normalize(search.trim()));
  }), [people, search, showHidden]);

  const replacePerson = (person: PersonDto) => setPeople((items) => items.map((item) => item.id === person.id ? toPerson(person) : item));
  const editLocal = (patch: Partial<Person>) => setPeople((items) => items.map((item) => item.id === selectedId ? { ...item, ...patch } : item));
  const saveSelected = () => {
    if (!selected) return;
    void updatePerson(selected.id, {
      name: selected.name, relationship: selected.relationship, birth: selected.birth || null,
      notes: selected.notes || null, active: selected.active,
    }).then(replacePerson).catch(load);
  };
  const togglePerson = (person: Person) => {
    const active = !person.active;
    setPeople((items) => items.map((item) => item.id === person.id ? { ...item, active } : item));
    void updatePerson(person.id, { active }).then(replacePerson).catch(load);
  };
  const submitPerson = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const created = await createPerson({
        name: String(data.get("name")), relationship: String(data.get("relationship")),
        birth: String(data.get("birth")) || null, notes: String(data.get("notes")) || null, active: true,
      });
      setPeople((items) => [...items, toPerson(created)]); setAdding(false); setSelectedId(created.id);
    } catch { setError(true); }
  };
  const removeFace = (faceId: string) => selected && void deleteFace(selected.id, faceId).then(replacePerson).catch(load);
  const saveFace = async () => {
    if (!selected || faceQuality == null) return;
    try { replacePerson(await addFace(selected.id, faceQuality)); setFaceFlow(false); setFaceQuality(null); } catch { load(); }
  };

  if (loading) return <section className="family-page page-wrap"><div className="family-empty"><RefreshCw /><h2>Đang tải người thân…</h2></div></section>;
  if (error && !people.length) return <section className="family-page page-wrap"><div className="family-empty"><AlertTriangle /><h2>Không tải được dữ liệu người thân</h2><button onClick={load}>Thử lại</button></div></section>;

  return <section className="family-page page-wrap">
    <header className="family-heading"><div><h1>Người thân</h1><p>Quản lý người quen để hệ thống nhận diện chính xác và giảm cảnh báo giả.</p></div><button onClick={() => setAdding(true)}><Plus /> Thêm người thân</button></header>
    <div className="family-toolbar">
      <label><Search /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Tìm theo tên hoặc mối quan hệ..." /></label>
      <div><span>Hiện cả người đã ẩn</span><button className={`family-switch ${showHidden ? "on" : ""}`} role="switch" aria-checked={showHidden} onClick={() => setShowHidden((value) => !value)}><i /></button></div>
      <aside className="family-total"><UsersRound /><span><strong>{visible.length}</strong><small>người thân</small></span></aside>
    </div>

    {visible.length ? <>
      <div className="family-table-wrap"><table className="family-table"><thead><tr><th>Ảnh</th><th>Tên</th><th>Mối quan hệ</th><th>Số ảnh khuôn mặt</th><th>Chất lượng nhận diện</th><th>Trạng thái</th><th>Hành động</th></tr></thead><tbody>
        {visible.map((person) => { const score = averageQuality(person); const quality = qualityInfo(score, person.faces.length); return <tr key={person.id} className={!person.active ? "hidden-person" : ""} onClick={() => setSelectedId(person.id)}>
          <td><PersonAvatar person={person} /></td><td><strong>{person.name}</strong></td><td><span className="relationship-badge">{person.relationship}</span></td>
          <td><span className="face-count"><Image /> {person.faces.length} ảnh khuôn mặt</span></td><td><div className={`recognition-quality ${quality.tone}`}><i /><span>{quality.label}</span>{person.faces.length > 0 && <small>{Math.round(score * 100)}%</small>}</div></td>
          <td><span className={`person-status ${person.active ? "active" : "hidden"}`}>{person.active ? "Đang hoạt động" : "Đã ẩn"}</span></td>
          <td><div className="family-row-actions"><button className="family-profile-link" onClick={(event) => { event.stopPropagation(); setSelectedId(person.id); }}>Xem hồ sơ</button><button onClick={(event) => { event.stopPropagation(); togglePerson(person); }}>{person.active ? "Vô hiệu hoá" : "Kích hoạt"}</button></div></td>
        </tr>; })}
      </tbody></table></div>
      <section className="family-mobile-list">{visible.map((person) => <button key={person.id} className={`family-mobile-card ${!person.active ? "hidden-person" : ""}`} onClick={() => setSelectedId(person.id)}><PersonAvatar person={person} /><span className="family-mobile-copy"><strong>{person.name}</strong><small>{person.relationship} · {person.faces.length} ảnh khuôn mặt</small></span><span className={`person-status ${person.active ? "active" : "hidden"}`}>{person.active ? "Hoạt động" : "Đã ẩn"}</span></button>)}</section>
    </> : <div className="family-empty"><UsersRound /><h2>Chưa có người thân phù hợp</h2><p>Thêm hồ sơ đầu tiên hoặc thay đổi bộ lọc tìm kiếm.</p><button onClick={() => setAdding(true)}>+ Thêm người thân</button></div>}

    {selected && <div className="family-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setSelectedId(null)}><article className="family-detail-modal">
      <header><div><PersonAvatar person={selected} large /><span><h2>{selected.name}</h2><p>{selected.relationship} · {selected.faces.length} ảnh khuôn mặt</p></span></div><button onClick={() => setSelectedId(null)}><X /></button></header>
      <div className="family-detail-scroll"><section className="family-basic-form"><div className="family-section-title"><h3>Thông tin cơ bản</h3><small>Dữ liệu được lưu trong SQLite trên Local Hub</small></div><div>
        <label><span>Tên hiển thị</span><input value={selected.name} onChange={(event) => editLocal({ name: event.target.value })} onBlur={saveSelected} /></label>
        <label><span>Mối quan hệ</span><input value={selected.relationship} onChange={(event) => editLocal({ relationship: event.target.value })} onBlur={saveSelected} /></label>
        <label><span>Ngày sinh</span><input type="date" value={selected.birth ?? ""} onChange={(event) => editLocal({ birth: event.target.value })} onBlur={saveSelected} /></label>
        <label className="notes"><span>Ghi chú</span><textarea value={selected.notes ?? ""} onChange={(event) => editLocal({ notes: event.target.value })} onBlur={saveSelected} /></label>
      </div></section>
      <section className="face-profiles-section"><div className="family-section-title row"><div><h3>Ảnh khuôn mặt đã đăng ký</h3><small>Embedding chỉ nằm trên Local Hub.</small></div><button onClick={() => setFaceFlow(true)}><Plus /> Thêm ảnh khuôn mặt</button></div>
        {selected.faces.length ? <div className="face-profile-grid">{selected.faces.map((face) => <div key={face.id} className="face-profile-card"><span className={`face-thumbnail ${selected.color}`}>{selected.name.split(" ").at(-1)?.[0]}</span><div><strong>{face.angle}</strong><small>{face.model}</small><div className="face-quality-bar good"><span><i style={{ width: `${face.quality * 100}%` }} /></span><b>{Math.round(face.quality * 100)}%</b></div></div><button title="Xóa ảnh" onClick={() => removeFace(face.id)}><Trash2 /></button></div>)}</div> : <div className="no-face-state"><Image /><strong>Chưa có ảnh khuôn mặt</strong><p>Thêm ảnh rõ mặt để bắt đầu nhận diện.</p></div>}
      </section>
      <section className={`person-active-setting ${!selected.active ? "warning" : ""}`}><div>{selected.active ? <ShieldCheck /> : <AlertTriangle />}<span><strong>Cho phép nhận diện người này</strong><small>{selected.active ? "Hệ thống đang coi đây là người quen." : "Người này có thể được đánh dấu là người lạ."}</small></span></div><button className={`family-switch ${selected.active ? "on" : ""}`} onClick={() => togglePerson(selected)}><i /></button></section>
      </div><footer><span><Check /> Thay đổi được lưu vào Local Hub</span><button onClick={() => setSelectedId(null)}>Đóng</button></footer>
    </article></div>}

    {adding && <div className="family-modal-backdrop"><form className="add-person-modal" onSubmit={submitPerson}><header><div><h2>Thêm người thân</h2><p>Tạo hồ sơ người quen mới.</p></div><button type="button" onClick={() => setAdding(false)}><X /></button></header><label><span>Tên hiển thị</span><input name="name" required /></label><label><span>Mối quan hệ</span><input name="relationship" required /></label><label><span>Ngày sinh</span><input name="birth" type="date" /></label><label><span>Ghi chú</span><textarea name="notes" /></label><footer><button type="button" onClick={() => setAdding(false)}>Huỷ</button><button type="submit">Thêm người thân</button></footer></form></div>}

    {faceFlow && selected && <div className="face-flow-backdrop"><article className="face-flow"><header><div><h2>Thêm ảnh khuôn mặt</h2><p>{selected.name}</p></div><button onClick={() => { setFaceFlow(false); setFaceQuality(null); }}><X /></button></header><div className="capture-guidance"><Camera /><div><strong>Chụp rõ mặt và đủ sáng</strong><p>Baseline đang mô phỏng điểm chất lượng; Vision Service sẽ cung cấp embedding thật.</p></div></div>{faceQuality == null ? <button className="capture-zone" onClick={() => setFaceQuality(Math.round((.55 + Math.random() * .4) * 100) / 100)}><Camera /><strong>Chụp ảnh mô phỏng</strong></button> : <div className="face-preview"><span className={selected.color}>{selected.name.split(" ").at(-1)?.[0]}</span><div className="good"><strong>Chất lượng ảnh: {Math.round(faceQuality * 100)}%</strong><div><i style={{ width: `${faceQuality * 100}%` }} /></div></div></div>}<footer><button onClick={() => setFaceQuality(null)}><RefreshCw /> Chụp lại</button><button className="upload-button" disabled={faceQuality == null} onClick={() => void saveFace()}>Lưu ảnh khuôn mặt</button></footer></article></div>}
  </section>;
}
