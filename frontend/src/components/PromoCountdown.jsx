import { useEffect, useState } from "react";
import { Clock } from "lucide-react";

function formatRemaining(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (days) return `${days} დღე ${hours} სთ`;
  if (hours) return `${hours} სთ ${minutes} წთ`;
  return `${minutes} წთ ${String(seconds).padStart(2, "0")} წმ`;
}

export default function PromoCountdown({ endsAt }) {
  const end = new Date(endsAt).getTime();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const remaining = end - now;
  if (!Number.isFinite(end) || remaining <= 0) return null;
  return (
    <p className="mt-0.5 flex items-center gap-1 font-mono text-[11px] font-semibold text-rose-600" data-testid="promo-countdown">
      <Clock className="h-3 w-3" />დარჩა {formatRemaining(remaining)}
    </p>
  );
}
