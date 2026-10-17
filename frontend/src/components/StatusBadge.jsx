import { cn } from "@/lib/utils";
import { useI18n } from "@/context/I18nContext";

const MAP = {
  Pending: "bg-amber-500/10 text-amber-500 border-amber-500/30",
  Processing: "bg-blue-500/10 text-blue-500 border-blue-500/30",
  "In Transit": "bg-indigo-500/10 text-indigo-400 border-indigo-500/30",
  Delivered: "bg-emerald-500/10 text-emerald-500 border-emerald-500/30",
  Cancelled: "bg-rose-500/10 text-rose-500 border-rose-500/30",
  active: "bg-emerald-500/10 text-emerald-500 border-emerald-500/30",
  pending: "bg-amber-500/10 text-amber-500 border-amber-500/30",
  suspended: "bg-rose-500/10 text-rose-500 border-rose-500/30",
};

export function StatusBadge({ status, testid }) {
  const { t } = useI18n();
  return (
    <span
      data-testid={testid || `status-badge-${status}`}
      className={cn("inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-wide", MAP[status] || "bg-muted text-muted-foreground border-border")}
    >
      {t(`status.${status}`)}
    </span>
  );
}
