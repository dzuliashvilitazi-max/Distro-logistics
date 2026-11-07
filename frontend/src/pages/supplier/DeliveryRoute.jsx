import { useCallback, useEffect, useState } from "react";
import { MapContainer, Marker, Polyline, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import GoogleTrafficMap from "@/components/GoogleTrafficMap";
import { isGoogleMapsConfigured, loadGoogleMapsApi, optimizeTrafficRoute } from "@/lib/googleMaps";
import { googleNavigationUrl, launchYandexNavigation } from "@/lib/navigation";
import { toast } from "sonner";
import {
  ArrowDown, ArrowUp, CalendarClock, Clock3, Copy, LocateFixed, MapPin, Navigation, Phone, Route as RouteIcon,
  Trash2, Truck, UserRound, Map as MapIcon, TriangleAlert,
} from "lucide-react";

import "leaflet/dist/leaflet.css";

const FALLBACK_CENTER = [41.7151, 44.8271];
const DEFAULT_WORKING_DAYS = [1, 2, 3, 4, 5];

function isoWeekday(dateValue) {
  const day = new Date(`${dateValue}T12:00:00`).getDay();
  return day === 0 ? 7 : day;
}

function numberedMarker(number, isOrigin = false) {
  const className = isOrigin ? "route-marker route-marker-origin" : "route-marker";
  const label = isOrigin ? "S" : number;
  return L.divIcon({
    className: "route-marker-container",
    html: `<span class="${className}">${label}</span>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

function FitRoute({ route, selectedStop }) {
  const map = useMap();
  const selected = route?.stops.find((stop) => stop.order_id === selectedStop);
  useEffect(() => {
    if (selected) {
      map.flyTo([selected.lat, selected.lon], Math.max(map.getZoom(), 14), { duration: 0.5 });
    } else if (route?.geometry?.length) {
      const bounds = L.latLngBounds(route.geometry.map(([lon, lat]) => [lat, lon]));
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
    }
  }, [map, route, selected]);
  return null;
}

function getCurrentPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("unsupported"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => resolve({ origin_lat: coords.latitude, origin_lon: coords.longitude }),
      reject,
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  });
}

function toDateTimeInputValue(date) {
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return localDate.toISOString().slice(0, 16);
}

function toDateInputValue(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export default function DeliveryRoute() {
  const { t, lang } = useI18n();
  const [route, setRoute] = useState(null);
  const [selectedStop, setSelectedStop] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [googleMapError, setGoogleMapError] = useState(false);
  const [savedRoutes, setSavedRoutes] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [activeOrders, setActiveOrders] = useState([]);
  const [selectedOrderIds, setSelectedOrderIds] = useState([]);
  const [driverId, setDriverId] = useState("");
  const [calendarDate, setCalendarDate] = useState(() => toDateInputValue(new Date()));
  const [scheduledAt, setScheduledAt] = useState(() => toDateTimeInputValue(new Date(Date.now() + 60 * 60 * 1000)));
  const [assignmentLoading, setAssignmentLoading] = useState(false);
  const [reordering, setReordering] = useState(false);
  const [shareUrl, setShareUrl] = useState("");
  const assignmentDate = scheduledAt.slice(0, 10);
  const eligibleDrivers = drivers.filter((driver) => driver.active !== false
    && (driver.working_days || DEFAULT_WORKING_DAYS).includes(isoWeekday(assignmentDate)));
  useEffect(() => {
    if (eligibleDrivers.some((driver) => driver.id === driverId)) return;
    setDriverId(eligibleDrivers[0]?.id || "");
  }, [eligibleDrivers, driverId]);
  const handleGoogleMapError = useCallback(() => {
    console.error("Could not load Google Maps traffic map; using the dark map fallback.");
    setGoogleMapError(true);
  }, []);
  const loadSavedRoutes = useCallback(async () => {
    try {
      const { data } = await api.get("/delivery-routes");
      setSavedRoutes(data);
    } catch (loadError) {
      console.error("Could not load saved delivery routes:", loadError);
      toast.error(formatApiError(loadError.response?.data?.detail) || t("route.loadRoutesError"));
    }
  }, [t]);

  const loadDispatchData = useCallback(async () => {
    try {
      const [{ data: nextDrivers }, { data: nextOrders }] = await Promise.all([
        api.get("/drivers"),
        api.get("/orders"),
      ]);
      setDrivers(nextDrivers);
      setActiveOrders(nextOrders.filter((order) => ["Processing", "In Transit"].includes(order.status)));
    } catch (loadError) {
      console.error("Could not load dispatcher data:", loadError);
      toast.error(formatApiError(loadError.response?.data?.detail) || t("route.loadRoutesError"));
    }
  }, [t]);

  useEffect(() => {
    loadSavedRoutes();
    loadDispatchData();
  }, [loadSavedRoutes, loadDispatchData]);

  const optimize = async (requestedOrderIds = selectedOrderIds) => {
    setLoading(true);
    setError("");
    try {
      let origin = {};
      try {
        origin = await getCurrentPosition();
      } catch {
        toast.message(t("route.locationFallback"));
      }
      const { data: optimizedRoute } = await api.post("/delivery-routes/optimize", {
        ...origin,
        ...(requestedOrderIds.length ? { order_ids: requestedOrderIds } : {}),
      });
      let nextRoute = optimizedRoute;
      if (isGoogleMapsConfigured) {
        try {
          const google = await loadGoogleMapsApi();
          const plannedDeparture = new Date(scheduledAt);
          const departureTime = plannedDeparture > new Date() ? plannedDeparture : new Date();
          nextRoute = await optimizeTrafficRoute(optimizedRoute, google, departureTime);
        } catch (trafficError) {
          console.error("Could not calculate a traffic-aware delivery route:", trafficError);
          toast.message(t("route.trafficUnavailable"));
        }
      }
      setRoute(nextRoute);
      setSelectedStop(null);
      setSelectedOrderIds([]);
      setShareUrl("");
      await loadSavedRoutes();
      await loadDispatchData();
    } catch (requestError) {
      console.error("Could not optimize delivery route:", requestError);
      const message = formatApiError(requestError.response?.data?.detail) || t("route.optimizeError");
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  const formatDuration = (seconds) => {
    const minutes = Math.round(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    if (hours === 0) return `${minutes} ${t("route.minutes")}`;
    return `${hours} ${t("route.hours")} ${remainder} ${t("route.minutes")}`;
  };
  const formatDistance = (meters) => `${(meters / 1000).toLocaleString(lang === "ka" ? "ka-GE" : lang, {
    maximumFractionDigits: 1,
  })} ${t("route.kilometers")}`;
  const assignRoute = async (event) => {
    event.preventDefault();
    if (!route?.id) return;
    setAssignmentLoading(true);
    try {
      const trafficRoute = route.trafficAware ? {
        geometry: route.geometry,
        stop_order: route.stops.map((stop) => stop.order_id),
        distance_meters: route.distance_meters,
        duration_seconds: route.duration_seconds,
      } : undefined;
      const { data } = await api.put(`/delivery-routes/${route.id}/assignment`, {
        driver_id: driverId,
        scheduled_at: new Date(scheduledAt).toISOString(),
        traffic_route: trafficRoute,
      });
      setRoute(data);
      setShareUrl("");
      toast.success(t("route.routeAssigned"));
      await loadSavedRoutes();
      await loadDispatchData();
    } catch (assignmentError) {
      console.error("Could not assign delivery route:", assignmentError);
      toast.error(formatApiError(assignmentError.response?.data?.detail) || t("route.assignError"));
    } finally {
      setAssignmentLoading(false);
    }
  };
  const removeRoute = async (routeId) => {
    try {
      await api.delete(`/delivery-routes/${routeId}`);
      setSavedRoutes((routes) => routes.filter((savedRoute) => savedRoute.id !== routeId));
      if (route?.id === routeId) {
        setRoute(null);
        setShareUrl("");
      }
      toast.success(t("route.routeRemoved"));
    } catch (deleteError) {
      console.error("Could not remove saved delivery route:", deleteError);
      toast.error(formatApiError(deleteError.response?.data?.detail) || t("route.removeError"));
    }
  };
  const moveStop = async (stopIndex, offset) => {
    if (!route?.id || reordering) return;
    const targetIndex = stopIndex + offset;
    if (targetIndex < 0 || targetIndex >= route.stops.length) return;
    const stopOrder = route.stops.map((stop) => stop.order_id);
    [stopOrder[stopIndex], stopOrder[targetIndex]] = [stopOrder[targetIndex], stopOrder[stopIndex]];
    setReordering(true);
    try {
      const { data } = await api.post(`/delivery-routes/${route.id}/reorder`, { stop_order: stopOrder });
      setRoute({ ...data, trafficAware: false });
      setShareUrl("");
      await loadSavedRoutes();
      toast.success(t("route.stopOrderUpdated"));
    } catch (reorderError) {
      console.error("Could not reorder delivery route stops:", reorderError);
      toast.error(formatApiError(reorderError.response?.data?.detail) || t("route.reorderError"));
    } finally {
      setReordering(false);
    }
  };
  const copyShareUrl = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      toast.success(t("route.linkCopied"));
    } catch (copyError) {
      console.error("Could not copy driver route link:", copyError);
      toast.error(t("route.copyError"));
    }
  };
  const dispatchRoute = async (method) => {
    if (!route || route.status !== "assigned") return;
    const popup = window.open("about:blank", "_blank");
    if (popup) popup.opener = null;
    try {
      let nextShareUrl = shareUrl;
      if (!nextShareUrl) {
        const { data } = await api.post(`/delivery-routes/${route.id}/dispatch`);
        nextShareUrl = `${window.location.origin}/driver/routes/${encodeURIComponent(data.share_token)}`;
        setShareUrl(nextShareUrl);
      }
      const message = `${t("route.dispatchMessage").replace("{driver}", route.driver_name).replace("{date}", new Date(route.scheduled_at).toLocaleString(lang === "ka" ? "ka-GE" : lang))}\n${nextShareUrl}`;
      const digits = String(route.driver_phone || "").replace(/\D/g, "");
      if (!digits) throw new Error(t("route.driverPhoneMissing"));
      const dispatchUrl = method === "whatsapp"
        ? `https://wa.me/${digits}?text=${encodeURIComponent(message)}`
        : `sms:${encodeURIComponent(route.driver_phone)}?body=${encodeURIComponent(message)}`;
      if (popup) {
        popup.location.href = dispatchUrl;
      } else {
        window.location.assign(dispatchUrl);
      }
    } catch (dispatchError) {
      popup?.close();
      console.error("Could not dispatch route to driver:", dispatchError);
      toast.error(formatApiError(dispatchError.response?.data?.detail) || dispatchError.message || t("route.dispatchError"));
    }
  };

  const assignedOrderIds = new Set(savedRoutes
    .filter((savedRoute) => savedRoute.status === "assigned")
    .flatMap((savedRoute) => savedRoute.stops.map((stop) => stop.order_id)));
  const availableOrders = activeOrders.filter((order) => !assignedOrderIds.has(order.id));
  const routesForDate = savedRoutes.filter((savedRoute) => savedRoute.scheduled_at
    && toDateInputValue(new Date(savedRoute.scheduled_at)) === calendarDate);
  const toggleOrderSelection = (orderId) => {
    setSelectedOrderIds((current) => current.includes(orderId)
      ? current.filter((selectedId) => selectedId !== orderId)
      : [...current, orderId]);
  };

  return (
    <div className="space-y-6" data-testid="delivery-route-page">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-highlight">{t("route.eyebrow")}</p>
          <h1 className="mt-2 flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
            <RouteIcon className="h-7 w-7 text-processing" />
            {t("route.title")}
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">{t("route.description")}</p>
        </div>
        <Button onClick={optimize} disabled={loading} className="h-11 shrink-0 px-5" data-testid="optimize-route-button">
          {loading ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent" /> : <LocateFixed className="h-4 w-4" />}
          {loading ? t("route.optimizing") : t("route.optimize")}
        </Button>
      </header>

      <p className="rounded-xl border border-info/20 bg-info/5 px-4 py-3 text-xs leading-relaxed text-muted-foreground">
        {t("route.providerNote")}
      </p>

      <section className="space-y-5 rounded-xl border border-border bg-card p-5 sm:p-6" aria-label={t("route.dispatchCalendar")} data-testid="dispatch-calendar">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-highlight">{t("route.dispatchCalendar")}</p>
            <h2 className="mt-1 text-lg font-semibold">{t("route.dailyDispatch")}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{t("route.calendarDescription")}</p>
          </div>
          <label className="space-y-1 text-xs font-medium text-muted-foreground">
            <span>{t("route.selectDispatchDay")}</span>
            <input
              type="date"
              value={calendarDate}
              onChange={(event) => {
                setCalendarDate(event.target.value);
                const time = scheduledAt.split("T")[1] || "09:00";
                setScheduledAt(`${event.target.value}T${time}`);
              }}
              className="block rounded-lg border border-border px-3 text-sm text-foreground"
              data-testid="dispatch-calendar-date"
            />
          </label>
        </div>

        <div className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-3">
            <h3 className="text-sm font-semibold">{t("route.routesForDay")}</h3>
            {routesForDate.length ? (
              <ul className="space-y-2">
                {routesForDate.map((scheduledRoute) => (
                  <li key={scheduledRoute.id} className="flex items-center gap-3 rounded-lg border border-border bg-secondary/30 p-3">
                    <button
                      type="button"
                      onClick={() => {
                        setRoute({ ...scheduledRoute, trafficAware: Boolean(scheduledRoute.traffic_aware) });
                        setSelectedStop(null);
                        setShareUrl("");
                        setDriverId(scheduledRoute.driver_id || "");
                        setScheduledAt(toDateTimeInputValue(new Date(scheduledRoute.scheduled_at)));
                      }}
                      className="min-w-0 flex-1 text-left"
                    >
                      <span className="block truncate font-mono text-xs font-semibold">{scheduledRoute.stops.length} · {scheduledRoute.id.slice(0, 8)}</span>
                      <span className="mt-1 block truncate text-xs text-muted-foreground">
                        {new Date(scheduledRoute.scheduled_at).toLocaleTimeString(lang === "ka" ? "ka-GE" : lang, { hour: "2-digit", minute: "2-digit" })}
                        {" · "}{scheduledRoute.driver_name}
                      </span>
                    </button>
                    <span className="rounded-full border border-delivered/30 bg-delivered/10 px-2 py-1 text-[10px] font-semibold text-delivered">{t("route.assigned")}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="rounded-lg border border-dashed border-border px-3 py-5 text-center text-xs text-muted-foreground">{t("route.noRoutesForDay")}</p>
            )}
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold">{t("route.ordersToSchedule")}</h3>
              <span className="font-mono text-xs text-muted-foreground">{availableOrders.length}</span>
            </div>
            {availableOrders.length ? (
              <>
                <ul className="max-h-48 space-y-2 overflow-y-auto">
                  {availableOrders.map((order) => (
                    <li key={order.id}>
                      <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border bg-secondary/30 p-3 text-xs">
                        <input
                          type="checkbox"
                          checked={selectedOrderIds.includes(order.id)}
                          onChange={() => toggleOrderSelection(order.id)}
                          className="mt-0.5 accent-[hsl(var(--primary))]"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-2 font-mono font-semibold text-foreground">
                            {order.order_no}
                            {(order.external_order || order.is_external) && <span className="rounded-full border border-highlight/30 bg-highlight/10 px-1.5 py-0.5 font-sans text-[9px] text-highlight">{t("orders.externalBadge")}</span>}
                          </span>
                          <span className="mt-1 block truncate text-muted-foreground">{order.retailer_name} · {order.delivery_address}</span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
                <Button
                  type="button"
                  onClick={() => optimize(selectedOrderIds)}
                  disabled={loading || selectedOrderIds.length === 0}
                  className="w-full"
                  data-testid="plan-selected-orders-button"
                >
                  <RouteIcon className="mr-2 h-4 w-4" />
                  {t("route.planSelectedOrders")} ({selectedOrderIds.length})
                </Button>
              </>
            ) : (
              <p className="rounded-lg border border-dashed border-border px-3 py-5 text-center text-xs text-muted-foreground">{t("route.noUnassignedOrders")}</p>
            )}
          </div>
        </div>
      </section>

      {savedRoutes.length > 0 && (
        <section className="rounded-xl border border-border bg-card p-4 sm:p-5" aria-label={t("route.savedRoutes")}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-highlight">{t("route.savedRoutes")}</p>
              <p className="mt-1 text-xs text-muted-foreground">{t("route.savedRoutesDescription")}</p>
            </div>
            <span className="rounded-full border border-border px-2.5 py-1 font-mono text-xs text-muted-foreground">{savedRoutes.length}</span>
          </div>
          <div className="mt-4 flex gap-2 overflow-x-auto pb-1">
            {savedRoutes.map((savedRoute) => (
              <div key={savedRoute.id} className={`flex min-w-56 items-center gap-2 rounded-lg border p-2 ${
                route?.id === savedRoute.id ? "border-processing/50 bg-processing/10" : "border-border bg-secondary/30"
              }`}>
                <button
                  type="button"
                  onClick={() => {
                    setRoute({ ...savedRoute, trafficAware: Boolean(savedRoute.traffic_aware) });
                    setSelectedStop(null);
                    setShareUrl("");
                    setDriverId(savedRoute.driver_id || "");
                    if (savedRoute.scheduled_at) setCalendarDate(toDateInputValue(new Date(savedRoute.scheduled_at)));
                    setScheduledAt(savedRoute.scheduled_at ? toDateTimeInputValue(new Date(savedRoute.scheduled_at)) : toDateTimeInputValue(new Date(Date.now() + 60 * 60 * 1000)));
                  }}
                  className="min-w-0 flex-1 text-left"
                >
                  <span className="block truncate font-mono text-xs font-semibold">{savedRoute.stops.length} · {savedRoute.id.slice(0, 8)}</span>
                  <span className="mt-1 block truncate text-[11px] text-muted-foreground">
                    {savedRoute.status === "assigned" ? `${t("route.assignedTo")} ${savedRoute.driver_name}` : t("route.draft")}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => removeRoute(savedRoute.id)}
                  className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  aria-label={t("route.removeRoute")}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      {route ? (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-border bg-card p-4">
              <p className="text-xs font-medium text-muted-foreground">{t("route.totalStops")}</p>
              <p className="mt-1 text-2xl font-bold text-foreground">{route.stops.length}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-4">
              <p className="text-xs font-medium text-muted-foreground">{t("route.estimatedDistance")}</p>
              <p className="mt-1 text-2xl font-bold text-foreground">{formatDistance(route.distance_meters)}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-4">
              <p className="text-xs font-medium text-muted-foreground">{t("route.estimatedDrivingTime")}</p>
              <p className="mt-1 text-2xl font-bold text-foreground">{formatDuration(route.duration_seconds)}</p>
            </div>
          </div>

          {route.unrouted_stops?.length > 0 && (
            <section className="rounded-lg border border-warning/30 bg-warning/5 p-4" role="alert" data-testid="unrouted-stops">
              <p className="flex items-center gap-2 text-sm font-semibold text-warning">
                <TriangleAlert className="h-4 w-4 shrink-0" />
                {t("route.unroutedWarning")}
              </p>
              <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                {route.unrouted_stops.map((stop) => (
                  <li key={stop.order_id}>{stop.order_no} · {stop.address || t("route.addressUnavailable")} · {t("route.coordinatesMissing")}</li>
                ))}
              </ul>
            </section>
          )}

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
                <>
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
                    <Polyline
                      positions={route.geometry.map(([lon, lat]) => [lat, lon])}
                      pathOptions={{ color: "#e5b94c", weight: 5, opacity: 0.9 }}
                    />
                    <Marker position={[route.origin.lat, route.origin.lon]} icon={numberedMarker(0, true)} />
                    {route.stops.map((stop) => (
                      <Marker
                        key={stop.order_id}
                        position={[stop.lat, stop.lon]}
                        icon={numberedMarker(stop.sequence)}
                        eventHandlers={{ click: () => setSelectedStop(stop.order_id) }}
                      />
                    ))}
                    <FitRoute route={route} selectedStop={selectedStop} />
                  </MapContainer>
                  <p className="px-3 pt-2 text-xs text-muted-foreground">
                    {googleMapError ? t("route.googleMapsUnavailable") : t("route.googleMapsSetup")}
                  </p>
                </>
              )}
              <div className="flex flex-wrap items-center gap-4 px-3 py-3 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-2"><span className="inline-block h-3 w-3 rounded-full bg-info" />{t("route.startPoint")}</span>
                <span className="inline-flex items-center gap-2"><span className="inline-block h-3 w-3 rounded-full bg-processing" />{t("route.deliveryStop")}</span>
                <span className="ml-auto">{route.provider}</span>
              </div>
            </section>

            <section className="rounded-xl border border-border bg-card p-5 sm:p-6" data-testid="optimized-stop-list">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-highlight">{t("route.routePlan")}</p>
                  <h2 className="mt-1 text-lg font-semibold text-foreground">{t("route.stopsInOrder")}</h2>
                </div>
                <span className="rounded-full border border-processing/30 bg-processing/10 px-2.5 py-1 text-xs font-semibold text-processing">
                  {route.stops.length}
                </span>
              </div>
              <div className="my-4 h-px bg-border" />
              <ol className="max-h-[480px] space-y-2 overflow-y-auto pr-1">
                {route.stops.map((stop, stopIndex) => (
                  <li key={stop.order_id}>
                    <div className={`rounded-xl border p-3 transition-all duration-200 ${
                      selectedStop === stop.order_id
                        ? "border-processing/50 bg-processing/10"
                        : "border-transparent bg-secondary/40 hover:border-border hover:bg-secondary/70"
                    }`}>
                      <button
                        type="button"
                        onClick={() => setSelectedStop(stop.order_id)}
                        aria-current={selectedStop === stop.order_id ? "step" : undefined}
                        className="flex w-full gap-3 text-left"
                      >
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-processing text-sm font-bold text-background">
                          {stop.sequence}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-xs font-semibold text-foreground">{stop.order_no}</span>
                            <span className="rounded-full bg-info/10 px-2 py-0.5 text-[10px] font-medium text-info">{t(`status.${stop.status}`)}</span>
                          </span>
                          <span className="mt-1 block truncate text-sm font-medium text-foreground">{stop.retailer_name}</span>
                          <span className="mt-1 flex items-start gap-1.5 text-xs leading-relaxed text-muted-foreground">
                            <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" />{stop.address}
                          </span>
                          {stop.delivery_window && (
                            <span className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                              <Clock3 className="h-3.5 w-3.5" />{stop.delivery_window}
                            </span>
                          )}
                        </span>
                        <Navigation className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
                      </button>
                      <div className="mt-3 flex gap-2 pl-11">
                        <button
                          type="button"
                          disabled={reordering || stopIndex === 0}
                          onClick={() => moveStop(stopIndex, -1)}
                          title={t("route.moveStopUp")}
                          aria-label={`${t("route.moveStopUp")} ${stop.order_no}`}
                          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-industrial-base/50 text-foreground transition-colors hover:border-highlight/50 hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          <ArrowUp className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          disabled={reordering || stopIndex === route.stops.length - 1}
                          onClick={() => moveStop(stopIndex, 1)}
                          title={t("route.moveStopDown")}
                          aria-label={`${t("route.moveStopDown")} ${stop.order_no}`}
                          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-industrial-base/50 text-foreground transition-colors hover:border-highlight/50 hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          <ArrowDown className="h-4 w-4" />
                        </button>
                        <a
                          href={googleNavigationUrl(stop.lat, stop.lon)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border bg-industrial-base/50 px-3 text-xs font-medium text-foreground transition-colors hover:border-highlight/50 hover:bg-secondary"
                          aria-label={`${t("route.googleNavigation")} ${stop.order_no}`}
                        >
                          <MapIcon className="h-3.5 w-3.5 text-highlight" />
                          {t("route.googleNavigation")}
                        </a>
                        <button
                          type="button"
                          onClick={() => launchYandexNavigation(stop.lat, stop.lon)}
                          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border bg-industrial-base/50 px-3 text-xs font-medium text-foreground transition-colors hover:border-highlight/50 hover:bg-secondary"
                          aria-label={`${t("route.yandexNavigation")} ${stop.order_no}`}
                        >
                          <Navigation className="h-3.5 w-3.5 text-processing" />
                          {t("route.yandexNavigation")}
                        </button>
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
              <a
                href={`https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route=${[
                  [route.origin.lat, route.origin.lon],
                  ...route.stops.map((stop) => [stop.lat, stop.lon]),
                ].map(([lat, lon]) => `${lat}%2C${lon}`).join("%3B")}`}
                target="_blank"
                rel="noreferrer"
                className="mt-4 flex h-11 w-full items-center justify-center gap-2 rounded-lg border border-border text-sm font-medium text-foreground transition-colors hover:border-highlight/50 hover:bg-secondary/60"
              >
                <Truck className="h-4 w-4 text-highlight" />
                {t("route.openNavigation")}
              </a>
              <form onSubmit={assignRoute} className="mt-5 space-y-4 border-t border-border pt-5" data-testid="route-assignment-form">
                <div>
                  <p className="flex items-center gap-2 text-sm font-semibold text-foreground"><CalendarClock className="h-4 w-4 text-highlight" />{t("route.scheduleAndAssign")}</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{eligibleDrivers.length ? t("route.scheduleDescription") : drivers.length ? t("drivers.noEligibleDrivers") : t("route.addDriverFirst")}</p>
                </div>
                {eligibleDrivers.length ? (
                  <label className="block space-y-1.5 text-xs font-medium text-muted-foreground">
                    <span className="flex items-center gap-1.5"><UserRound className="h-3.5 w-3.5" />{t("route.selectDriver")}</span>
                    <select
                      required
                      value={driverId}
                      onChange={(event) => setDriverId(event.target.value)}
                      className="w-full rounded-lg border border-border px-3 text-sm text-foreground"
                      data-testid="route-driver-select"
                    >
                      <option value="">{t("route.chooseDriver")}</option>
                      {eligibleDrivers.map((driver) => <option key={driver.id} value={driver.id}>{driver.name} · {driver.phone}{driver.vehicle_plate ? ` · ${driver.vehicle_plate}` : ""}</option>)}
                    </select>
                  </label>
                ) : (
                  <a href="/supplier/drivers" className="block rounded-lg border border-highlight/30 bg-highlight/5 p-3 text-sm font-medium text-highlight hover:bg-highlight/10">{drivers.length ? t("drivers.noEligibleDrivers") : t("route.addDriverFirst")}</a>
                )}
                <label className="block space-y-1.5 text-xs font-medium text-muted-foreground">
                  <span>{t("route.scheduledAt")}</span>
                  <input
                    required
                    type="datetime-local"
                    min={toDateTimeInputValue(new Date())}
                    value={scheduledAt}
                    onChange={(event) => {
                      setScheduledAt(event.target.value);
                      if (event.target.value) setCalendarDate(event.target.value.slice(0, 10));
                    }}
                    className="w-full rounded-lg border border-border px-3 text-sm text-foreground"
                  />
                </label>
                <Button type="submit" disabled={assignmentLoading || !eligibleDrivers.length || !driverId} className="w-full" data-testid="assign-route-button">
                  {assignmentLoading ? t("route.assigning") : t("route.scheduleAndAssign")}
                </Button>
                {shareUrl && (
                  <div className="space-y-2 rounded-lg border border-delivered/30 bg-delivered/5 p-3" data-testid="driver-route-share-link">
                    <p className="text-xs font-semibold text-delivered">{t("route.driverLinkReady")}</p>
                    <div className="flex gap-2">
                      <input readOnly value={shareUrl} className="min-w-0 flex-1 rounded-md border border-border px-2 text-xs text-foreground" aria-label={t("route.driverShareLink")} />
                      <Button type="button" variant="outline" size="icon" onClick={copyShareUrl} aria-label={t("route.copyLink")}>
                        <Copy className="h-4 w-4" />
                      </Button>
                    </div>
                    <p className="text-[11px] leading-relaxed text-muted-foreground">{t("route.linkExpiry")}</p>
                  </div>
                )}
                {route.status === "assigned" && (
                  <div className="grid grid-cols-2 gap-2">
                    <Button type="button" variant="outline" onClick={() => dispatchRoute("whatsapp")} data-testid="send-route-whatsapp-button">
                      <Phone className="mr-2 h-4 w-4 text-delivered" />{t("route.sendWhatsApp")}
                    </Button>
                    <Button type="button" variant="outline" onClick={() => dispatchRoute("sms")} data-testid="send-route-sms-button">
                      <Phone className="mr-2 h-4 w-4 text-highlight" />{t("route.sendSMS")}
                    </Button>
                  </div>
                )}
              </form>
            </section>
          </div>
        </>
      ) : (
        <div className="flex min-h-72 flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/50 px-6 py-12 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-processing/20 bg-processing/10">
            <RouteIcon className="h-7 w-7 text-processing" />
          </div>
          <h2 className="mt-4 text-lg font-semibold text-foreground">{t("route.emptyTitle")}</h2>
          <p className="mt-2 max-w-lg text-sm leading-relaxed text-muted-foreground">{error || t("route.emptyDescription")}</p>
        </div>
      )}
    </div>
  );
}
