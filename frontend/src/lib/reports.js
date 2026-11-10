import { format, endOfMonth, startOfMonth, startOfYear, subDays, subMonths, parseISO } from "date-fns";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";

export const money = (value) => (value === null || value === undefined ? "—" : `₾${Number(value).toFixed(2)}`);

export const dateLabel = (value) => value && !Number.isNaN(new Date(value).getTime())
  ? new Date(value).toLocaleDateString("ka-GE", { timeZone: "Asia/Tbilisi" }) : "—";

export const PAYMENT_LABELS = {
  paid: "გადახდილი", unpaid: "გადაუხდელი", partially_paid: "ნაწილობრივ გადახდილი", overdue: "ვადაგადაცილებული",
};

export const PAYMENT_STYLES = {
  paid: "border-emerald-500/30 bg-emerald-500/10 text-emerald-500",
  unpaid: "border-amber-500/30 bg-amber-500/10 text-amber-500",
  partially_paid: "border-sky-500/30 bg-sky-500/10 text-sky-500",
  overdue: "border-rose-500/30 bg-rose-500/10 text-rose-500",
};

export const COMMISSION_LABELS = {
  settled_at_checkout: "დაკავებულია გადახდისას",
  invoiced: "შეტანილია საკომისიო ინვოისში",
  accrued: "დარიცხულია, ინვოისი ჯერ არ არის",
  cancelled: "გაუქმებულია",
};

export const PRESETS = [
  ["today", "დღეს"], ["7", "ბოლო 7 დღე"], ["30", "ბოლო 30 დღე"], ["month", "მიმდინარე თვე"],
  ["previous", "წინა თვე"], ["year", "მიმდინარე წელი"], ["all", "მთელი პერიოდი"], ["custom", "თარიღების არჩევა"],
];

const day = (date) => format(date, "yyyy-MM-dd");

export function presetRange(preset) {
  const today = parseISO(new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Tbilisi" }));
  if (preset === "today") return [day(today), day(today)];
  if (preset === "7") return [day(subDays(today, 6)), day(today)];
  if (preset === "30") return [day(subDays(today, 29)), day(today)];
  if (preset === "month") return [day(startOfMonth(today)), day(today)];
  if (preset === "previous") {
    const previous = subMonths(today, 1);
    return [day(startOfMonth(previous)), day(endOfMonth(previous))];
  }
  if (preset === "year") return [day(startOfYear(today)), day(today)];
  return ["", ""];
}

export const cleanParams = (params) => Object.fromEntries(
  Object.entries(params).filter(([, value]) => value !== "" && value !== null && value !== undefined && value !== "all"),
);

export async function downloadReport(path, params, fmt, name) {
  try {
    const response = await api.get(path, { params: { ...cleanParams(params), format: fmt }, responseType: "blob" });
    const url = URL.createObjectURL(response.data);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${name}.${fmt}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (error) {
    toast.error(formatApiError(error.response?.data?.detail) || "ექსპორტი ვერ მოხერხდა");
  }
}

export async function fetchInvoiceBlob(orderId) {
  const response = await api.get(`/orders/${encodeURIComponent(orderId)}/invoice.pdf`, { responseType: "blob" });
  return new Blob([response.data], { type: "application/pdf" });
}
