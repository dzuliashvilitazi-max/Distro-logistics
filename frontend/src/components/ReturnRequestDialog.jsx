import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

const REASONS = ["damaged", "wrong_item", "expired", "quality_issue", "other"];

export default function ReturnRequestDialog({ order, item, onClose, onSubmitted }) {
  const { t } = useI18n();
  const [quantity, setQuantity] = useState("1");
  const [reason, setReason] = useState("damaged");
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!item) return;
    setQuantity("1");
    setReason("damaged");
    setComment("");
  }, [item]);

  const submit = async (event) => {
    event.preventDefault();
    if (!order || !item || saving) return;
    setSaving(true);
    try {
      await api.post("/returns", {
        order_id: order.id,
        product_id: item.product_id,
        quantity: Number(quantity),
        reason,
        comment: comment.trim(),
      });
      toast.success(t("returns.requestSent"));
      onSubmitted?.();
      onClose();
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={!!item} onOpenChange={(open) => { if (!open && !saving) onClose(); }}>
      <DialogContent className="bg-card sm:max-w-md" data-testid="return-request-dialog">
        <DialogHeader>
          <DialogTitle>{t("returns.request")}</DialogTitle>
          <DialogDescription>{order?.order_no} · {item?.name}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={submit}>
          <label className="block space-y-1 text-sm">
            <span>{t("returns.quantity")}</span>
            <Input type="number" min="1" max={item?.quantity || 1} step="1" value={quantity}
              onChange={(event) => setQuantity(event.target.value)} required data-testid="return-quantity" />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{t("returns.reason")}</span>
            <select className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground"
              value={reason} onChange={(event) => setReason(event.target.value)} data-testid="return-reason">
              {REASONS.map((value) => <option key={value} value={value}>{t(`returns.reasons.${value}`)}</option>)}
            </select>
          </label>
          <label className="block space-y-1 text-sm">
            <span>{t("returns.comment")}</span>
            <Textarea value={comment} onChange={(event) => setComment(event.target.value)} maxLength={1000} rows={3} />
          </label>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={saving}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={saving || Number(quantity) < 1}>
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t("returns.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
