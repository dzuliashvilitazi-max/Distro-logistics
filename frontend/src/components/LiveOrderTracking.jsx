import { useEffect, useState } from "react";
import { MapContainer, Marker, Polyline, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import { Loader2, MapPin, Radio } from "lucide-react";
import { API, api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import "leaflet/dist/leaflet.css";

const FALLBACK_CENTER = [41.7151, 44.8271];

function locationIcon(label, kind) {
  return L.divIcon({
    className: "route-marker-container",
    html: `<span class="route-marker ${kind}">${label}</span>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });
}

function FitTrackingMap({ tracking }) {
  const map = useMap();
  useEffect(() => {
    const points = [];
    if (tracking?.driver_location) points.push([tracking.driver_location.lat, tracking.driver_location.lon]);
    if (tracking?.destination) points.push([tracking.destination.lat, tracking.destination.lon]);
    if (points.length === 1) map.flyTo(points[0], 13, { duration: 0.4 });
    else if (points.length > 1) map.fitBounds(L.latLngBounds(points), { padding: [28, 28], maxZoom: 14 });
  }, [tracking, map]);
  return null;
}

function trackingSocketUrl(orderId) {
  const root = API.replace(/^http:/, "ws:").replace(/^https:/, "wss:").replace(/\/api\/?$/, "");
  return `${root}/ws/orders/${encodeURIComponent(orderId)}/tracking`;
}

export default function LiveOrderTracking({ order }) {
  const { t, lang } = useI18n();
  const [tracking, setTracking] = useState(null);
  const [loading, setLoading] = useState(true);
  const [closed, setClosed] = useState(false);
  const [error, setError] = useState("");
  const locale = lang === "ka" ? "ka-GE" : lang === "ru" ? "ru-RU" : "en";

  useEffect(() => {
    let active = true;
    let socket;
    let reconnectTimer;
    const loadSnapshot = async () => {
      try {
        const { data } = await api.get(`/orders/${encodeURIComponent(order.id)}/tracking`);
        if (active) setTracking(data);
      } catch (requestError) {
        if (!active) return;
        if (requestError.response?.status === 409) setClosed(true);
        else setError(formatApiError(requestError.response?.data?.detail));
      } finally {
        if (active) setLoading(false);
      }
    };
    const connect = () => {
      if (!active) return;
      socket = new WebSocket(trackingSocketUrl(order.id));
      socket.onopen = () => {
        const token = localStorage.getItem("distro_token");
        if (!token) {
          socket.close(1008, "Missing access token");
          return;
        }
        socket.send(JSON.stringify({ token }));
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === "snapshot" || message.type === "location") {
            setTracking((current) => ({ ...current, ...message }));
          }
          if (message.type === "status" && message.status !== "In Transit") setClosed(true);
        } catch (parseError) {
          console.error("Invalid order tracking event:", parseError);
        }
      };
      socket.onclose = (event) => {
        if (event.code === 1008) setClosed(true);
        if (active && event.code !== 1008) reconnectTimer = window.setTimeout(connect, 3000);
      };
      socket.onerror = () => socket.close();
    };
    loadSnapshot();
    connect();
    return () => {
      active = false;
      window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [order.id]);

  if (closed) return null;
  const driver = tracking?.driver_location;
  const destination = tracking?.destination;
  const center = driver ? [driver.lat, driver.lon] : destination ? [destination.lat, destination.lon] : FALLBACK_CENTER;

  return (
    <section className="mt-4 overflow-hidden rounded-lg border border-highlight/25 bg-card" data-testid={`live-order-tracking-${order.id}`}>
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2.5">
        <span className="flex items-center gap-2 text-xs font-semibold"><MapPin className="h-3.5 w-3.5 text-highlight" />{t("tracking.orderTitle")}</span>
        <span className="flex items-center gap-1.5 text-[10px] font-medium text-delivered"><Radio className="h-3 w-3 animate-pulse" />{t("tracking.live")}</span>
      </header>
      <div className="relative h-48 w-full sm:h-56">
        <MapContainer center={center} zoom={12} scrollWheelZoom={false} dragging className="h-full w-full">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          />
          {driver && <Marker position={[driver.lat, driver.lon]} icon={locationIcon("D", "route-marker-origin")} />}
          {destination && <Marker position={[destination.lat, destination.lon]} icon={locationIcon("S", "route-marker")} />}
          {driver && destination && <Polyline positions={[[driver.lat, driver.lon], [destination.lat, destination.lon]]} pathOptions={{ color: "#e5b94c", weight: 3, dashArray: "6 6" }} />}
          <FitTrackingMap tracking={tracking} />
        </MapContainer>
        {loading && <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-background/45"><span className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />{t("tracking.loading")}</span></div>}
        {!loading && !driver && <div className="pointer-events-none absolute bottom-2 left-2 flex items-center gap-1.5 rounded-md border border-border bg-card/95 px-2 py-1 text-[10px] text-muted-foreground">{t("tracking.waitingForGps")}</div>}
      </div>
      <footer className="flex flex-wrap justify-between gap-2 px-3 py-2 text-[10px] text-muted-foreground">
        <span>{tracking?.driver_name || t("tracking.driver")}</span>
        {driver?.recorded_at && <time>{t("tracking.updated")} {new Date(driver.recorded_at).toLocaleTimeString(locale)}</time>}
        {error && <span role="alert" className="text-destructive">{error}</span>}
      </footer>
    </section>
  );
}