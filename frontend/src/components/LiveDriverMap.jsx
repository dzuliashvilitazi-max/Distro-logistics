import { useEffect, useState } from "react";
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import { Loader2, LocateFixed, Radio } from "lucide-react";
import { API, api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { useSupplierWarehouse } from "@/context/SupplierWarehouseContext";
import "leaflet/dist/leaflet.css";

const FALLBACK_CENTER = [41.7151, 44.8271];

function driverIcon() {
  return L.divIcon({
    className: "route-marker-container",
    html: '<span class="route-marker route-marker-origin">D</span>',
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

function FitDrivers({ drivers }) {
  const map = useMap();
  useEffect(() => {
    const points = drivers
      .filter((driver) => driver.driver_location)
      .map((driver) => [driver.driver_location.lat, driver.driver_location.lon]);
    if (points.length === 1) map.flyTo(points[0], 13, { duration: 0.4 });
    else if (points.length > 1) map.fitBounds(L.latLngBounds(points), { padding: [36, 36], maxZoom: 13 });
  }, [drivers, map]);
  return null;
}

function websocketUrl(warehouseId) {
  const root = API.replace(/^http:/, "ws:").replace(/^https:/, "wss:").replace(/\/api\/?$/, "");
  const url = new URL(`${root}/ws/supplier/live-drivers`);
  if (warehouseId && warehouseId !== "all") url.searchParams.set("warehouse_id", warehouseId);
  return url.toString();
}

export default function LiveDriverMap() {
  const { t, lang } = useI18n();
  const { activeWarehouseId } = useSupplierWarehouse();
  const [drivers, setDrivers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let socket;
    let reconnectTimer;
    const loadSnapshot = async () => {
      try {
        const { data } = await api.get("/supplier/live-drivers");
        if (active) setDrivers(data.drivers || []);
      } catch (requestError) {
        if (active) setError(formatApiError(requestError.response?.data?.detail));
      } finally {
        if (active) setLoading(false);
      }
    };
    const connect = () => {
      if (!active) return;
      socket = new WebSocket(websocketUrl(activeWarehouseId));
      socket.onopen = () => {
        const token = localStorage.getItem("distro_token");
        if (!token) {
          socket.close(1008, "Missing access token");
          return;
        }
        socket.send(JSON.stringify({ token }));
        setConnected(true);
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === "snapshot") setDrivers(message.drivers || []);
          if (message.type === "location") {
            setDrivers((current) => {
              const index = current.findIndex((driver) => driver.route_id === message.route_id);
              if (index < 0) return [...current, {
                route_id: message.route_id, driver_id: message.driver_id, driver_name: message.driver_name,
                driver_phone: message.driver_phone, warehouse_id: message.warehouse_id,
                driver_location: message.driver_location, geometry: message.geometry, orders: [],
              }];
              return current.map((driver) => driver.route_id === message.route_id
                ? { ...driver, ...message }
                : driver);
            });
          }
          if (message.type === "route_completed") {
            setDrivers((current) => current.filter((driver) => driver.route_id !== message.route_id));
          }
        } catch (parseError) {
          console.error("Invalid driver tracking event:", parseError);
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (active) reconnectTimer = window.setTimeout(connect, 3000);
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
  }, [activeWarehouseId]);

  const locatedDrivers = drivers.filter((driver) => driver.driver_location
    && Number.isFinite(Number(driver.driver_location.lat))
    && Number.isFinite(Number(driver.driver_location.lon)));
  const locale = lang === "ka" ? "ka-GE" : lang === "ru" ? "ru-RU" : "en";

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-card" data-testid="live-driver-map">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 sm:px-5">
        <div className="flex items-center gap-2.5">
          <LocateFixed className="h-4 w-4 text-highlight" />
          <div>
            <h2 className="text-sm font-semibold">{t("tracking.driversTitle")}</h2>
            <p className="text-xs text-muted-foreground">{t("tracking.driversDescription")}</p>
          </div>
        </div>
        <span className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[10px] font-semibold ${connected ? "border-delivered/30 bg-delivered/10 text-delivered" : "border-border text-muted-foreground"}`}>
          <Radio className={`h-3 w-3 ${connected ? "animate-pulse" : ""}`} />{connected ? t("tracking.live") : t("tracking.connecting")}
        </span>
      </header>
      <div className="relative h-[300px] w-full sm:h-[390px]">
        <MapContainer center={FALLBACK_CENTER} zoom={11} scrollWheelZoom className="h-full w-full">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          />
          {locatedDrivers.map((driver) => (
            <Marker key={driver.route_id} position={[driver.driver_location.lat, driver.driver_location.lon]} icon={driverIcon()}>
              <Popup>
                <strong>{driver.driver_name}</strong><br />
                {driver.driver_phone}<br />
                {driver.orders?.map((order) => order.order_no).join(", ")}<br />
                {driver.driver_location.recorded_at && new Date(driver.driver_location.recorded_at).toLocaleTimeString(locale)}
              </Popup>
            </Marker>
          ))}
          {locatedDrivers.map((driver) => driver.geometry?.length > 1 && (
            <Polyline key={`route-${driver.route_id}`} positions={driver.geometry.map(([lon, lat]) => [lat, lon])}
              pathOptions={{ color: "#e5b94c", weight: 3, opacity: 0.5 }} />
          ))}
          <FitDrivers drivers={locatedDrivers} />
        </MapContainer>
        {(loading || (!locatedDrivers.length && !error)) && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-background/45">
            <div className="flex items-center gap-2 rounded-md border border-border bg-card/95 px-3 py-2 text-xs text-muted-foreground">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <LocateFixed className="h-4 w-4" />}
              {loading ? t("tracking.loading") : t("tracking.waitingForDrivers")}
            </div>
          </div>
        )}
      </div>
      {error && <p role="alert" className="border-t border-border px-4 py-2 text-xs text-destructive">{error}</p>}
      {locatedDrivers.length > 0 && (
        <ul className="divide-y divide-border" aria-label={t("tracking.activeDrivers")}>
          {locatedDrivers.map((driver) => (
            <li key={driver.route_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-xs sm:px-5">
              <span className="font-medium">{driver.driver_name} <span className="font-normal text-muted-foreground">· {driver.orders?.length || 0} {t("tracking.deliveries")}</span></span>
              <time className="font-mono text-muted-foreground">{driver.driver_location.recorded_at ? new Date(driver.driver_location.recorded_at).toLocaleTimeString(locale) : "—"}</time>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}