import { cn } from "@/lib/utils";
import { useI18n } from "@/context/I18nContext";

const MAP = {
  "Pending Payment": "bg-amber-500/10 text-amber-600 border-amber-500/30",
  Pending: "bg-processing/10 text-processing border-processing/30",
  Processing: "bg-processing/10 text-processing border-processing/30",
  "In Transit": "bg-highlight/10 text-highlight border-highlight/30",
  Delivered: "bg-delivered/15 text-delivered border-delivered/40",
  Cancelled: "bg-rose-500/10 text-rose-500 border-rose-500/30",
  Rejected: "bg-rose-500/10 text-rose-500 border-rose-500/30",
  active: "bg-delivered/10 text-delivered border-delivered/30",
  pending: "bg-processing/10 text-processing border-processing/30",
  suspended: "bg-rose-500/10 text-rose-500 border-rose-500/30",
  paid: "bg-delivered/10 text-delivered border-delivered/30",
  overdue: "bg-rose-500/10 text-rose-500 border-rose-500/30",
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
