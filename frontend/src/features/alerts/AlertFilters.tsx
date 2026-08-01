import type { AlertFilter } from "./alert.types";

const filters: { id: AlertFilter; label: string }[] = [
  { id: "all", label: "Tất cả" }, { id: "pending", label: "Chờ xử lý" },
  { id: "critical", label: "Khẩn cấp" }, { id: "resolved", label: "Đã xử lý" },
];

export function AlertFilters({ value, onChange }: { value: AlertFilter; onChange: (value: AlertFilter) => void }) {
  return <div className="alert-filter-chips" aria-label="Lọc cảnh báo">{filters.map((filter) =>
    <button key={filter.id} className={value === filter.id ? "active" : ""} onClick={() => onChange(filter.id)}>{filter.label}</button>)}</div>;
}

