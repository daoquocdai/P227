import type { LucideIcon } from "lucide-react";
export default function PagePlaceholder({ icon: Icon, title, description }: { icon: LucideIcon; title: string; description: string }) { return <section className="page-wrap"><div className="page-heading"><div><h1>{title}</h1><p>{description}</p></div></div><div className="section-card page-placeholder"><Icon /><h2>{title}</h2><p>Màn hình này đã có route và file riêng, sẵn sàng để phát triển độc lập ở task tiếp theo.</p></div></section>; }

