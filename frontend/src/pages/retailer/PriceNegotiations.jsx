import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, requestErrorMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Check, MessageSquare, X } from "lucide-react";
import { toast } from "sonner";

export default function PriceNegotiations() {
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [countering, setCountering] = useState(null);
  const [counterPrice, setCounterPrice] = useState("");
  const [comment, setComment] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/price-negotiations/mine");
      setItems(data);
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = searchParams.get("negotiation_id");
    if (!id || loading) return;
    document.querySelector(`[data-testid="store-negotiation-${CSS.escape(id)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [items, loading, searchParams]);

  const respond = async (item, action, counter = null) => {
    setBusyId(item.id);
    try {
      await api.post(`/price-negotiations/${encodeURIComponent(item.id)}/store-response`, {
        action,
        counter_price: counter == null ? null : Number(counter),
        comment,
      });
      toast.success(action === "ACCEPT" ? "შეთავაზება მიღებულია და შეკვეთა შეიქმნა" :
        action === "REJECT" ? "კონტრ-შეთავაზება უარყოფილია" : "ხელახალი შეთავაზება გაგზავნილია");
      setCountering(null);
      setComment("");
      await load();
    } catch (error) {
      toast.error(requestErrorMessage(error));
    } finally {
      setBusyId("");
    }
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">ფასის მოთხოვნები / შევაჭრებები</h1>
        <p className="mt-1 text-sm text-muted-foreground">იხილეთ თქვენი მოთხოვნები და უპასუხეთ დისტრიბუტორის კონტრ-შეთავაზებას.</p>
      </div>
      {loading ? <p className="py-10 text-center text-sm text-muted-foreground">იტვირთება...</p>
        : items.length === 0 ? <p className="rounded-xl border border-dashed border-border py-16 text-center text-sm text-muted-foreground">ღია ფასის მოთხოვნები არ არის</p>
          : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {items.map((item) => {
              const countered = item.status === "COUNTERED";
              const distributor = item.distributor?.business_name || item.distributor?.name || item.distributor_id;
              return (
                <div key={item.id} className="rounded-xl border border-border bg-card p-4" data-testid={`store-negotiation-${item.id}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold">{item.product_name}</p>
                      <p className="text-sm text-muted-foreground">{distributor}</p>
                    </div>
                    <Badge variant={countered ? "default" : "outline"}>{countered ? "პასუხი მიღებულია" : "მოლოდინში"}</Badge>
                  </div>
                  <div className="mt-3 space-y-1 text-sm">
                    <p>რაოდენობა: <strong>{item.quantity}</strong></p>
                    <p>თქვენი ფასი: <strong>₾{Number(item.proposed_price).toFixed(2)}</strong> / ერთეული</p>
                    {countered && <p>კონტრ-შეთავაზება: <strong className="text-primary">₾{Number(item.counter_price).toFixed(2)}</strong> / ერთეული</p>}
                    {countered && item.counter_comment && <p className="text-muted-foreground">{item.counter_comment}</p>}
                    {!countered && item.comment && <p className="text-muted-foreground">{item.comment}</p>}
                  </div>
                  {countered && <div className="mt-4 flex flex-wrap gap-2">
                    <Button size="sm" disabled={!!busyId} onClick={() => respond(item, "ACCEPT")} data-testid={`accept-counter-${item.id}`}><Check className="mr-1 h-4 w-4" />მიღება</Button>
                    <Button size="sm" variant="outline" disabled={!!busyId} onClick={() => { setCountering(item); setCounterPrice(String(item.counter_price)); setComment(""); }} data-testid={`renegotiate-${item.id}`}><MessageSquare className="mr-1 h-4 w-4" />ხელახლა შევაჭრება</Button>
                    <Button size="sm" variant="ghost" disabled={!!busyId} onClick={() => respond(item, "REJECT")} data-testid={`reject-counter-${item.id}`}><X className="mr-1 h-4 w-4" />უარყოფა</Button>
                  </div>}
                </div>
              );
            })}
          </div>}

      <Dialog open={!!countering} onOpenChange={(open) => !open && setCountering(null)}>
        <DialogContent className="bg-card sm:max-w-md">
          <DialogHeader>
            <DialogTitle>ხელახლა შევაჭრება</DialogTitle>
            <DialogDescription>{countering?.product_name}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input type="number" min="0" step="0.01" value={counterPrice} onChange={(e) => setCounterPrice(e.target.value)} placeholder="თქვენი ფასი (₾)" data-testid="store-counter-price" />
            <Textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="კომენტარი (არასავალდებულო)" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCountering(null)}>გაუქმება</Button>
            <Button disabled={!counterPrice || Number(counterPrice) < 0 || !!busyId} onClick={() => respond(countering, "COUNTER", counterPrice)} data-testid="send-store-counter">გაგზავნა</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
