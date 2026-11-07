import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { MapContainer, Marker, Polyline, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import GoogleTrafficMap from "@/components/GoogleTrafficMap";
import { isGoogleMapsConfigured } from "@/lib/googleMaps";
import { googleNavigationUrl, launchYandexNavigation, wazeNavigationUrl } from "@/lib/navigation";
import { toast } from "sonner";
import { CalendarClock, CheckCircle2, Clock3, Loader2, Map as MapIcon, MapPin, Navigation, Phone, Play, Route as RouteIcon } from "lucide-react";

import "leaflet/dist/leaflet.css";

const FALLBACK_CENTER = [41.7151, 44.8271];

function numberedMarker(number, isOrigin = false) {
  const className = isOrigin ? "route-marker route-marker-origin" : "route-marker";
  return L.divIcon({
    className: "route-marker-container",
    html: `<span class="${className}">${isOrigin ? "S" : number}</span>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

function FitSharedRoute({ geometry }) {
  const map = useMap();
  useEffect(() => {
    if (geometry?.length) {
      map.fitBounds(L.latLngBounds(geometry.map(([lon, lat]) => [lat, lon])), { padding: [40, 40], maxZoom: 13 });
    }
  }, [geometry, map]);
  return null;
}

export default function DriverRoute() {
  const { token: pathToken } = useParams();
  const [searchParams] = useSearchParams();
  const token = pathToken || searchParams.get("token");
  const { t, lang } = useI18n();
  const [route, setRoute] = useState(null);
  const [selectedStop, setSelectedStop] = useState(null);
  const [error, setError] = useState("");
  const [googleMapError, setGoogleMapError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deliveringId, setDeliveringId] = useState(null);
  const [gpsError, setGpsError] = useState("");
  const [wakeLockStatus, setWakeLockStatus] = useState("");
  const handleGoogleMapError = useCallback(() => {
    console.error("Could not load Google Maps for the shared driver route.");
    setGoogleMapError(true);
  }, []);

  useEffect(() => {
    let active = true;
    api.get(`/delivery-routes/shared/${encodeURIComponent(token)}`).then(({ data }) => {
      if (active) setRoute(data);
    }).catch((requestError) => {
      console.error("Could not load shared driver route:", requestError);
      if (active) setError(formatApiError(requestError.response?.data?.detail) || t("route.sharedRouteError"));
    });
    return () => { active = false; };
  }, [token, t]);

  const reloadRoute = useCallback(async () => {
    const { data } = await api.get(`/delivery-routes/shared/${encodeURIComponent(token)}`);
    setRoute(data);
  }, [token]);

  useEffect(() => {
    if (!route?.tracking_active) return undefined;
    if (!navigator.geolocation) {
      setGpsError(t("tracking.gpsUnavailable"));
      return undefined;
    }
    let active = true;
    let lastSentAt = 0;
    setGpsError("");
    const watchId = navigator.geolocation.watchPosition(async ({ coords }) => {
      if (!active || Date.now() - lastSentAt < 10000) return;
      lastSentAt = Date.now();
      const location = {
        lat: coords.latitude,
        lon: coords.longitude,
        accuracy_meters: Number.isFinite(coords.accuracy) ? coords.accuracy : undefined,
      };
      try {
        const { data } = await api.post(`/delivery-routes/shared/${encodeURIComponent(token)}/location`, location);
        if (!active) return;
        const deliveredIds = new Set(data.delivered_order_ids || []);
        setRoute((current) => current && ({
          ...current,
          driver_location: { ...location, recorded_at: data.recorded_at },
          tracking_active: data.tracking_active,
          stops: current.stops.map((stop) => deliveredIds.has(stop.order_id)
            ? { ...stop, status: "Delivered", lifecycle_status: "DELIVERED" }
            : stop),
        }));
        if (deliveredIds.size) toast.success(t("driver.geofenceDelivered"));
      } catch (locationError) {
        if (!active) return;
        if (locationError.response?.status === 409) {
          setGpsError(t("tracking.routeEnded"));
          return;
        }
        console.error("Could not send driver GPS location:", locationError);
        setGpsError(t("tracking.gpsSendError"));
      }
    }, () => {
      if (active) setGpsError(t("tracking.gpsPermissionError"));
    }, { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 });
    return () => {
      active = false;
      navigator.geolocation.clearWatch(watchId);
    };
  }, [route?.tracking_active, token, t]);

  useEffect(() => {
    if (!route?.tracking_active) return undefined;
    const wakeLock = navigator.wakeLock;
    if (!wakeLock?.request) {
      setWakeLockStatus("unavailable");
      return undefined;
    }
    let active = true;
    let requesting = false;
    let sentinel = null;
    setWakeLockStatus("unavailable");

    const requestWakeLock = async () => {
      if (!active || requesting || document.visibilityState !== "visible" || sentinel && !sentinel.released) return;
      requesting = true;
      try {
        const lock = await wakeLock.request("screen");
        if (!active) {
          await lock.release();
          return;
        }
        sentinel = lock;
        setWakeLockStatus("active");
        lock.addEventListener("release", () => {
          if (active) setWakeLockStatus("unavailable");
        }, { once: true });
      } catch (wakeLockError) {
        if (active) setWakeLockStatus("unavailable");
      } finally {
        requesting = false;
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") void requestWakeLock();
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    void requestWakeLock();

    return () => {
      active = false;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      if (sentinel && !sentinel.released) void sentinel.release();
    };
  }, [route?.tracking_active]);

  const startRoute = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/delivery-routes/shared/${encodeURIComponent(token)}/start`);
      const startedIds = new Set(data.in_transit || []);
      setRoute((current) => current && ({
        ...current,
        tracking_active: data.tracking_active,
        stops: current.stops.map((stop) => startedIds.has(stop.order_id)
          ? { ...stop, status: "In Transit", lifecycle_status: "IN_TRANSIT" }
          : stop),
      }));
      toast.success(t("driver.routeStarted"));
      await reloadRoute();
    } catch (requestError) { toast.error(formatApiError(requestError.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const deliver = async (stop, payment) => {
    setBusy(true);
    try {
      await api.post(`/delivery-routes/shared/${encodeURIComponent(token)}/orders/${stop.order_id}/deliver`, { payment });
      setDeliveringId(null);
      await reloadRoute();
    } catch (requestError) { toast.error(formatApiError(requestError.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  if (!route) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-5 py-12 text-foreground">
        <section className="w-full max-w-lg rounded-xl border border-border bg-card p-8 text-center">
          <RouteIcon className={`mx-auto h-8 w-8 ${error ? "text-destructive" : "animate-pulse text-processing"}`} />
          <h1 className="mt-4 text-xl font-semibold">{error ? t("route.sharedRouteUnavailable") : t("route.loadingSharedRoute")}</h1>
          {error && <p className="mt-2 text-sm text-muted-foreground">{error}</p>}
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-background px-4 py-6 text-foreground sm:px-6 sm:py-10" data-testid="driver-route-page">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="rounded-xl border border-border bg-card p-5 sm:p-6">
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-highlight">{t("route.driverView")}</p>
          <h1 className="mt-2 flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
            <RouteIcon className="h-7 w-7 text-processing" />
            {t("route.assignedRoute")}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">{route.supplier_name}</p>
          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-2"><span className="font-medium text-foreground">{t("route.driverName")}:</span>{route.driver_name}</span>
            <span className="inline-flex items-center gap-2"><Phone className="h-4 w-4 text-highlight" />{route.driver_phone}</span>
            <span className="inline-flex items-center gap-2"><CalendarClock className="h-4 w-4 text-highlight" />{new Date(route.scheduled_at).toLocaleString(lang === "ka" ? "ka-GE" : lang)}</span>
          </div>
          {route.tracking_active && wakeLockStatus && (
            <p role="status" className="mt-3 text-xs text-muted-foreground">
              {t(wakeLockStatus === "active" ? "driver.screenAwake" : "driver.keepScreenAwake")}
            </p>
          )}
          {route.stops.some((stop) => stop.status === "Processing") && (
            <Button type="button" className="mt-4 h-12 w-full text-base font-bold sm:w-auto" disabled={busy} onClick={startRoute} data-testid="start-route">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}{t("driver.startRoute")}
            </Button>
          )}
        </header>

        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(330px,0.9fr)]">
          <section className="overflow-hidden rounded-xl border border-border bg-card p-2 shadow-sm" aria-label={t("route.mapLabel")}>
            {isGoogleMapsConfigured && !googleMapError ? (
              <GoogleTrafficMap
                route={route}
                selectedStop={selectedStop}
                onLoadError={handleGoogleMapError}
                onSelectStop={setSelectedStop}
              />
            ) : (
              <MapContainer
                center={route.origin ? [route.origin.lat, route.origin.lon] : FALLBACK_CENTER}
                zoom={11}
                scrollWheelZoom
                className="h-[420px] w-full rounded-lg sm:h-[560px]"
                data-testid="delivery-route-map"
              >
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
                  url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                />
                <Polyline positions={route.geometry.map(([lon, lat]) => [lat, lon])} pathOptions={{ color: "#e5b94c", weight: 5, opacity: 0.9 }} />
                <Marker position={[route.origin.lat, route.origin.lon]} icon={numberedMarker(0, true)} />
                {route.stops.map((stop) => (
                  <Marker
                    key={stop.order_id}
                    position={[stop.lat, stop.lon]}
                    icon={numberedMarker(stop.sequence)}
                    eventHandlers={{ click: () => setSelectedStop(stop.order_id) }}
                  />
                ))}
                <FitSharedRoute geometry={route.geometry} />
              </MapContainer>
            )}
            <div className="flex flex-wrap items-center gap-4 px-3 py-3 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-2"><span className="h-3 w-3 rounded-full bg-info" />{t("route.startPoint")}</span>
              <span className="inline-flex items-center gap-2"><span className="h-3 w-3 rounded-full bg-processing" />{t("route.deliveryStop")}</span>
              <span className="ml-auto">{route.provider}</span>
            </div>
          </section>
          {gpsError && <p role="status" className="rounded-lg border border-processing/30 bg-processing/5 px-3 py-2 text-xs text-muted-foreground">{gpsError}</p>}

          <section className="order-first rounded-xl border border-border bg-card p-5 sm:p-6 xl:order-none">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-highlight">{t("route.routePlan")}</p>
                <h2 className="mt-1 text-lg font-semibold">{t("route.stopsInOrder")}</h2>
              </div>
              <span className="rounded-full border border-processing/30 bg-processing/10 px-2.5 py-1 text-xs font-semibold text-processing">{route.stops.length}</span>
            </div>
            <div className="my-4 h-px bg-border" />
            <ol className="max-h-[560px] space-y-2 overflow-y-auto pr-1">
              {route.stops.map((stop) => (
                <li key={stop.order_id} className={`rounded-xl border p-3 ${selectedStop === stop.order_id ? "border-processing/50 bg-processing/10" : "border-transparent bg-secondary/40"}`}>
                  <button type="button" onClick={() => setSelectedStop(stop.order_id)} className="flex w-full gap-3 text-left">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-processing text-sm font-bold text-background">{stop.sequence}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs font-semibold">{stop.order_no}</span>
                        <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium">{t(`status.${stop.status}`)}</span>
                      </span>
                      {(stop.is_external || stop.external_order) && (
                        <span className="ml-2 rounded-full border border-highlight/30 bg-highlight/10 px-1.5 py-0.5 font-sans text-[9px] font-semibold text-highlight">
                          {t("orders.externalBadge")}
                        </span>
                      )}
                      <span className="mt-1 block truncate text-sm font-medium">{stop.retailer_name}</span>
                      <span className="mt-1 flex items-start gap-1.5 text-xs leading-relaxed text-muted-foreground"><MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" />{stop.address}</span>
                      {stop.delivery_window && <span className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground"><Clock3 className="h-3.5 w-3.5" />{stop.delivery_window}</span>}
                    </span>
                  </button>
                  <div className="mt-2 space-y-1 pl-11 text-xs">
                    {(stop.items || []).length > 0 && <p className="text-muted-foreground"><span className="font-semibold text-foreground">{t("driver.items")}:</span> {stop.items.map((item) => `${item.name} × ${item.quantity}`).join(", ")}</p>}
                    {stop.paymentStatus && (
                      <p className={stop.paymentStatus === "PAID" ? "font-semibold text-emerald-500" : "font-semibold text-amber-500"} data-testid={`stop-payment-${stop.order_id}`}>
                        {t(`pay.${stop.paymentStatus}`)}{stop.balance > 0 && ` · ${t("pay.balance")} ₾${Number(stop.balance).toFixed(2)}`}
                      </p>
                    )}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2 pl-11">
                    <a href={googleNavigationUrl(stop.lat, stop.lon)} target="_blank" rel="noopener noreferrer" className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-border bg-industrial-base/50 px-3 text-xs font-medium transition-colors hover:border-highlight/50 hover:bg-secondary">
                      <MapIcon className="h-3.5 w-3.5 text-highlight" />{t("driver.googleMaps")}
                    </a>
                    <a href={wazeNavigationUrl(stop.lat, stop.lon)} target="_blank" rel="noopener noreferrer" className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-border bg-industrial-base/50 px-3 text-xs font-medium transition-colors hover:border-highlight/50 hover:bg-secondary">
                      <Navigation className="h-3.5 w-3.5 text-info" />{t("driver.waze")}
                    </a>
                    <Button type="button" variant="outline" size="sm" onClick={() => launchYandexNavigation(stop.lat, stop.lon)} className="h-10 px-3 text-xs">
                      <Navigation className="h-3.5 w-3.5 text-processing" />{t("route.yandexNavigation")}
                    </Button>
                  </div>
                  {stop.status === "Delivered" ? (
                    <p className="mt-3 flex items-center gap-1.5 pl-11 text-sm font-semibold text-emerald-500"><CheckCircle2 className="h-4 w-4" />{t("driver.delivered")}</p>
                  ) : ["Processing", "In Transit"].includes(stop.status) && (
                    <div className="mt-3 pl-11">
                      {stop.status === "In Transit" && route.tracking_active && (
                        <p className="mb-2 text-xs text-muted-foreground" role="status">{t("driver.geofenceWaiting")}</p>
                      )}
                      {deliveringId === stop.order_id ? (
                        <div className="space-y-2 rounded-lg border border-border bg-background/60 p-3">
                          <p className="text-xs font-semibold">{t("driver.paymentOnDelivery")}</p>
                          {stop.paymentStatus === "PAID" ? (
                            <Button type="button" className="h-12 w-full text-base" disabled={busy} onClick={() => deliver(stop, "cash")} data-testid={`confirm-delivery-${stop.order_id}`}>
                              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}{t("driver.confirmDelivery")}
                            </Button>
                          ) : (
                            <div className="grid gap-2">
                              <Button type="button" className="h-12 w-full text-base" disabled={busy} onClick={() => deliver(stop, "cash")} data-testid={`deliver-cash-${stop.order_id}`}>{t("driver.cashCollected")}</Button>
                              <Button type="button" variant="outline" className="h-12 w-full text-base" disabled={busy} onClick={() => deliver(stop, "credit")} data-testid={`deliver-credit-${stop.order_id}`}>{t("driver.onCredit")}</Button>
                            </div>
                          )}
                          <Button type="button" variant="ghost" size="sm" className="w-full" onClick={() => setDeliveringId(null)}>{t("common.cancel")}</Button>
                        </div>
                      ) : (
                        <Button type="button" className="h-12 w-full text-base font-bold" onClick={() => setDeliveringId(stop.order_id)} data-testid={`deliver-${stop.order_id}`}>
                          <CheckCircle2 className="h-5 w-5" />{t("driver.deliver")}
                        </Button>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>
    </main>
  );
}
