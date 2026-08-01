import { AlertTriangle, RefreshCw, Search } from "lucide-react";
import { AlertFilters } from "./AlertFilters";
import { AlertListItem } from "./AlertListItem";
import type { AlertEvent, AlertFilter } from "./alert.types";

export function AlertList({ alerts, selectedId, loading, error, search, filter, onSearch, onFilter, onSelect, onRetry }: {
  alerts: AlertEvent[]; selectedId: string; loading: boolean; error: boolean; search: string; filter: AlertFilter;
  onSearch: (value: string) => void; onFilter: (value: AlertFilter) => void; onSelect: (id: string) => void; onRetry: () => void;
}) {
  return <aside className="alerts-list-panel" aria-label="Danh sách cảnh báo">
    <div className="alert-list-tools">
      <label className="alert-search"><Search /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Tìm cảnh báo..." /></label>
      <AlertFilters value={filter} onChange={onFilter} />
    </div>
    <div className="alert-list-scroll">
      {loading && Array.from({ length: 5 }, (_, index) => <div className="alert-skeleton" key={index}><i /><span /><span /></div>)}
      {!loading && error && <div className="alert-list-state"><AlertTriangle /><strong>Chưa thể tải cảnh báo</strong><p>Đây là lỗi mô phỏng. Bạn có thể thử lại.</p><button onClick={onRetry}><RefreshCw /> Thử lại</button></div>}
      {!loading && !error && alerts.length === 0 && <div className="alert-list-state"><Search /><strong>Không tìm thấy cảnh báo</strong><p>Hãy thử từ khóa hoặc bộ lọc khác.</p></div>}
      {!loading && !error && alerts.map((alert) => <AlertListItem key={alert.id} alert={alert} selected={selectedId === alert.id} onSelect={() => onSelect(alert.id)} />)}
    </div>
  </aside>;
}

