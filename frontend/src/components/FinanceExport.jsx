import { useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Download, Loader2 } from "lucide-react";
import { toast } from "sonner";

export default function FinanceExport({ dateFrom = "", dateTo = "" }) {
  const [busy, setBusy] = useState(false);

  const download = async () => {
    if (dateFrom && dateTo && dateFrom > dateTo) {
      toast.error("საწყისი თარიღი არ უნდა აღემატებოდეს საბოლოო თარიღს.");
      return;
    }
    setBusy(true);
    try {
      const params = {};
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      const { data } = await api.get("/finance/export.xlsx", { params, responseType: "blob" });
      const url = URL.createObjectURL(data);
      const link = document.createElement("a");
      link.href = url;
      link.download = `finance-${dateFrom || "start"}_${dateTo || "today"}.xlsx`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (error) {
      let detail = error.response?.data?.detail;
      if (error.response?.data instanceof Blob) {
        try { detail = JSON.parse(await error.response.data.text()).detail; } catch { detail = undefined; }
      }
      toast.error(formatApiError(detail) || "ექსპორტი ვერ მოხერხდა.");
    } finally {
      setBusy(false);
    }
  };

  return (
      <Button type="button" onClick={download} disabled={busy} data-testid="finance-export">
        {busy ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Download className="mr-1.5 h-4 w-4" />}
        ფინანსური ექსპორტი (Excel)
      </Button>
  );
}
