import { useCallback, useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import AddressMapPicker from "@/components/AddressMapPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { isGoogleMapsConfigured, loadGoogleMapsApi, optimizeTrafficRoute } from "@/lib/googleMaps";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  CalendarDays, ChevronLeft, ChevronRight, Copy, Link2, MessageCircle,
  MessageSquareText, Pencil, Phone, Plus, Save, Trash2, Truck, X,
} from "lucide-react";

const WORK_DAYS = [
  { value: 1, label: "ორშაბათი" },
  { value: 2, label: "სამშაბათი" },
  { value: 3, label: "ოთხშაბათი" },
  { value: 4, label: "ხუთშაბათი" },
  { value: 5, label: "პარასკევი" },
  { value: 6, label: "შაბათი" },
  { value: 7, label: "კვირა" },
];
const DEFAULT_WORKING_DAYS = [1, 2, 3, 4, 5];
const EMPTY_DRIVER = { name: "", phone: "", vehicle_plate: "", personal_id: "", transport_type: "", working_days: DEFAULT_WORKING_DAYS, active: true };
const EMPTY_EXTERNAL_ORDER = {
  customer_name: "", customer_phone: "", delivery_address: "", city: "", lat: null, lng: null, item_name: "",
  quantity: "1", unit_price: "", notes: "", delivery_window: "",
};
const fallbackTranslate = (key) => key;

function toDateInputValue(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function toDateTimeInputValue(date) {
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return localDate.toISOString().slice(0, 16);
}

function isoWeekday(dateValue) {
  const day = new Date(`${dateValue}T12:00:00`).getDay();
  return day === 0 ? 7 : day;
}

const INITIAL_SCHEDULE = toDateTimeInputValue(new Date(Date.now() + 60 * 60 * 1000));

function getWeekDates(dateValue) {
  const date = new Date(`${dateValue}T12:00:00`);
  const mondayOffset = (date.getDay() + 6) % 7;
  date.setDate(date.getDate() - mondayOffset);
  return Array.from({ length: 7 }, (_, index) => {
    const day = new Date(date);
    day.setDate(day.getDate() + index);
    return toDateInputValue(day);
  });
}

export default function SupplierDrivers() {
  const i18n = useI18n();
  const t = i18n?.t || fallbackTranslate;
  const lang = i18n?.lang || "en";
  const [drivers, setDrivers] = useState([]);
  const [routes, setRoutes] = useState([]);
  const [activeOrders, setActiveOrders] = useState([]);
  const [form, setForm] = useState(EMPTY_DRIVER);
  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dispatchView, setDispatchView] = useState("week");
  const [selectedDate, setSelectedDate] = useState(() => INITIAL_SCHEDULE.slice(0, 10));
  const [selectedDriverId, setSelectedDriverId] = useState("");
  const [selectedOrderIds, setSelectedOrderIds] = useState([]);
  const [manualOrder, setManualOrder] = useState(EMPTY_EXTERNAL_ORDER);
  const [scheduleTime, setScheduleTime] = useState(() => INITIAL_SCHEDULE.slice(11));
  const [scheduling, setScheduling] = useState(false);
  const [creatingExternalOrder, setCreatingExternalOrder] = useState(false);
  const [dispatchingRouteId, setDispatchingRouteId] = useState("");
  const [dispatchLink, setDispatchLink] = useState(null);
  const locale = lang === "ka" ? "ka-GE" : lang === "ru" ? "ru-RU" : "en";
  const weekDates = useMemo(() => getWeekDates(selectedDate), [selectedDate]);
  const eligibleDrivers = drivers.filter((driver) => driver.active !== false
    && (driver.working_days || DEFAULT_WORKING_DAYS).includes(isoWeekday(selectedDate)));

  useEffect(() => {
    if (eligibleDrivers.some((driver) => driver.id === selectedDriverId)) return;
    setSelectedDriverId(eligibleDrivers[0]?.id || "");
  }, [eligibleDrivers, selectedDriverId]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [{ data: nextDrivers }, { data: nextRoutes }, { data: nextOrders }] = await Promise.all([
        api.get("/drivers"),
        api.get("/delivery-routes"),
        api.get("/orders"),
      ]);
      setDrivers(nextDrivers);
      setRoutes(nextRoutes);
      setActiveOrders(nextOrders.filter((order) => ["Processing", "In Transit"].includes(order.status)));
    } catch (error) {
      console.error("Could not load driver dispatch data:", error);
      toast.error(formatApiError(error.response?.data?.detail) || t("drivers.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const saveDriver = async (event) => {
    event.preventDefault();
    if (!form.working_days.length) {
      toast.error(t("drivers.workingDayRequired"));
      return;
    }
    setSaving(true);
    try {
      const { data } = editingId
        ? await api.put(`/drivers/${editingId}`, form)
        : await api.post("/drivers", form);
      setDrivers((current) => {
        const next = editingId
          ? current.map((driver) => driver.id === editingId ? data : driver)
          : [...current, data];
        return next.sort((a, b) => a.name.localeCompare(b.name));
      });
      setForm(EMPTY_DRIVER);
      setEditingId(null);
      toast.success(t(editingId ? "drivers.updated" : "drivers.added"));
    } catch (error) {
      console.error("Could not save distributor driver:", error);
      toast.error(formatApiError(error.response?.data?.detail) || t("drivers.saveError"));
    } finally {
      setSaving(false);
    }
  };

  const removeDriver = async (driverId) => {
    try {
      await api.delete(`/drivers/${driverId}`);
      setDrivers((current) => current.filter((driver) => driver.id !== driverId));
      if (editingId === driverId) {
        setEditingId(null);
        setForm(EMPTY_DRIVER);
      }
      toast.success(t("drivers.removed"));
      await loadData();
    } catch (error) {
      console.error("Could not remove distributor driver:", error);
      toast.error(formatApiError(error.response?.data?.detail) || t("drivers.removeError"));
    }
  };

  const editDriver = (driver) => {
    setEditingId(driver.id);
    setForm({
      name: driver.name,
      phone: driver.phone,
      vehicle_plate: driver.vehicle_plate || "",
      personal_id: driver.personal_id || "",
      transport_type: driver.transport_type || "",
      working_days: driver.working_days || DEFAULT_WORKING_DAYS,
      active: driver.active !== false,
    });
  };

  const routesForDateAndDriver = (date, driverId) => routes.filter((route) => route.status === "assigned"
    && route.driver_id === driverId
    && route.scheduled_at
    && toDateInputValue(new Date(route.scheduled_at)) === date);

  const eligibleDriversForDate = (date) => drivers.filter((driver) => driver.active !== false
    && (driver.working_days || DEFAULT_WORKING_DAYS).includes(isoWeekday(date)));

  const selectDispatchDay = (date, driverId = selectedDriverId) => {
    setSelectedDate(date);
    const dayDrivers = eligibleDriversForDate(date);
    const assignedDriverId = dayDrivers.some((driver) => driver.id === driverId)
      ? driverId
      : dayDrivers[0]?.id || "";
    setSelectedDriverId(assignedDriverId);
    const routeOrderIds = routesForDateAndDriver(date, assignedDriverId)
      .flatMap((route) => route.stops.map((stop) => stop.order_id))
      .filter((orderId) => activeOrders.some((order) => order.id === orderId));
    setSelectedOrderIds(routeOrderIds);
  };

  const selectDispatchDriver = (driverId) => {
    setSelectedDriverId(driverId);
    const routeOrderIds = routesForDateAndDriver(selectedDate, driverId)
      .flatMap((route) => route.stops.map((stop) => stop.order_id))
      .filter((orderId) => activeOrders.some((order) => order.id === orderId));
    setSelectedOrderIds(routeOrderIds);
  };

  const toggleOrderSelection = (orderId) => {
    setSelectedOrderIds((current) => current.includes(orderId)
      ? current.filter((id) => id !== orderId)
      : [...current, orderId]);
  };

  const createCalendarExternalOrder = async (event) => {
    event.preventDefault();
    if (!Number.isFinite(manualOrder.lat) || !Number.isFinite(manualOrder.lng) || !manualOrder.delivery_address) {
      toast.error(t("checkout.pinAddress"));
      return;
    }
    setCreatingExternalOrder(true);
    try {
      const { data } = await api.post("/external-orders", {
        ...manualOrder,
        quantity: Number(manualOrder.quantity),
        unit_price: Number(manualOrder.unit_price),
        external_order: true,
      });
      setActiveOrders((current) => [data, ...current]);
      setSelectedOrderIds((current) => [...new Set([...current, data.id])]);
      setManualOrder(EMPTY_EXTERNAL_ORDER);
      toast.success(t("orders.externalCreated"));
    } catch (error) {
      console.error("Could not create an external order from the dispatch calendar:", error);
      toast.error(formatApiError(error.response?.data?.detail) || t("orders.externalCreateError"));
    } finally {
      setCreatingExternalOrder(false);
    }
  };

  const scheduleRoute = async (event) => {
    event.preventDefault();
    if (!selectedDriverId || !selectedOrderIds.length) return;
    setScheduling(true);
    try {
      const routesToReplace = routesForDateAndDriver(selectedDate, selectedDriverId);
      const replaceRouteIds = routesToReplace.map((route) => route.id);
      const scheduledAt = new Date(`${selectedDate}T${scheduleTime}`);
      const { data: optimizedRoute } = await api.post("/delivery-routes/optimize", {
        order_ids: selectedOrderIds,
        replace_route_ids: replaceRouteIds,
      });
      let route = optimizedRoute;
      if (isGoogleMapsConfigured) {
        try {
          const google = await loadGoogleMapsApi();
          route = await optimizeTrafficRoute(optimizedRoute, google);
        } catch (trafficError) {
          console.error("Could not optimize the combined route with live traffic:", trafficError);
          toast.message(t("route.trafficUnavailable"));
        }
      }
      const trafficRoute = route.trafficAware ? {
        geometry: route.geometry,
        stop_order: route.stops.map((stop) => stop.order_id),
        distance_meters: route.distance_meters,
        duration_seconds: route.duration_seconds,
      } : undefined;
      await api.put(`/delivery-routes/${route.id}/assignment`, {
        driver_id: selectedDriverId,
        scheduled_at: scheduledAt.toISOString(),
        traffic_route: trafficRoute,
        replace_route_ids: replaceRouteIds,
      });
      toast.success(t("drivers.routeScheduled"));
      setSelectedOrderIds([]);
      await loadData();
    } catch (error) {
      console.error("Could not optimize and schedule combined delivery route:", error);
      toast.error(formatApiError(error.response?.data?.detail) || t("route.optimizeError"));
    } finally {
      setScheduling(false);
    }
  };

  const generateDispatchLink = async (route) => {
    setDispatchingRouteId(route.id);
    try {
      const { data } = await api.post(`/delivery-routes/${route.id}/dispatch`);
      const url = `${window.location.origin}/m/driver-route?token=${encodeURIComponent(data.share_token)}`;
      setDispatchLink({ route, url });
    } catch (error) {
      console.error("Could not generate a driver dispatch link:", error);
      toast.error(formatApiError(error.response?.data?.detail) || t("route.dispatchError"));
    } finally {
      setDispatchingRouteId("");
    }
  };

  const dispatchMessage = dispatchLink
    ? `${t("drivers.dispatchMessage").replace("{driver}", dispatchLink.route.driver_name).replace(
      "{date}",
      new Date(dispatchLink.route.scheduled_at).toLocaleDateString(locale),
    )}\n${dispatchLink.url}`
    : "";
  const smsPhone = dispatchLink?.route.driver_phone?.replace(/[^\d+]/g, "") || "";
  const whatsappPhone = dispatchLink?.route.driver_phone?.replace(/\D/g, "") || "";
  const smsUrl = `sms:${smsPhone}?body=${encodeURIComponent(dispatchMessage)}`;
  const whatsappUrl = `https://wa.me/${whatsappPhone}?text=${encodeURIComponent(dispatchMessage)}`;

  const routesForDate = (date) => routes.filter((route) => route.status === "assigned"
    && route.scheduled_at
    && toDateInputValue(new Date(route.scheduled_at)) === date);
  const routeLabel = (route) => `${route.stops?.length || 0} · ${route.id.slice(0, 8)}`;
  const formatDay = (date, options) => new Date(`${date}T12:00:00`).toLocaleDateString(locale, options);
  const georgianWeekday = (date) => WORK_DAYS[isoWeekday(date) - 1].label;
  const routesForSelectedDriver = routesForDateAndDriver(selectedDate, selectedDriverId);
  const replaceRouteIds = routesForSelectedDriver.map((route) => route.id);
  const alreadyAssignedElsewhere = new Set(routes
    .filter((route) => route.status === "assigned" && !replaceRouteIds.includes(route.id))
    .flatMap((route) => route.stops.map((stop) => stop.order_id)));
  const selectableOrders = activeOrders.filter((order) => !alreadyAssignedElsewhere.has(order.id));

  const changeWeek = (amount) => {
    const date = new Date(`${selectedDate}T12:00:00`);
    date.setDate(date.getDate() + amount * 7);
    setSelectedDate(toDateInputValue(date));
  };

  const renderAssignedRoutes = (date) => {
    const assignedRoutes = routesForDate(date);
    if (!assignedRoutes.length) {
      return <p className="py-4 text-center text-xs text-muted-foreground">{t("drivers.noRoutesForDay")}</p>;
    }
    return (
      <ul className="space-y-2">
        {assignedRoutes.map((route) => (
          <li key={route.id} className="rounded-lg border border-border bg-secondary/30 p-3" data-testid={`driver-assigned-route-${route.id}`}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-mono text-xs font-semibold">{routeLabel(route)}</span>
              <span className="text-xs text-muted-foreground">
                {new Date(route.scheduled_at).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })}
              </span>
            </div>
            <p className="mt-1 truncate text-xs text-muted-foreground">
              <Truck className="mr-1 inline h-3.5 w-3.5" />{route.driver_name}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-3 w-full"
              onClick={() => generateDispatchLink(route)}
              disabled={dispatchingRouteId === route.id}
              data-testid={`dispatch-driver-route-${route.id}`}
            >
              <MessageSquareText className="mr-2 h-4 w-4" />
              {dispatchingRouteId === route.id ? t("route.dispatching") : t("drivers.sendRoute")}
            </Button>
          </li>
        ))}
      </ul>
    );
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6" data-testid="supplier-drivers-page">
      <header>
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-highlight">{t("drivers.eyebrow")}</p>
        <h1 className="mt-2 flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
          <Truck className="h-7 w-7 text-processing" />{t("drivers.title")}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">{t("drivers.description")}</p>
      </header>

      <form onSubmit={saveDriver} className="space-y-4 rounded-xl border border-border bg-card p-5" data-testid="driver-form">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground">
          <span>{t("drivers.name")}</span>
          <input
            required
            maxLength={120}
            value={form.name}
            onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            className="w-full rounded-lg border border-border px-3 text-sm text-foreground"
            autoComplete="name"
          />
        </label>
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground">
          <span>{t("drivers.phone")}</span>
          <input
            required
            type="tel"
            maxLength={40}
            value={form.phone}
            onChange={(event) => setForm((current) => ({ ...current, phone: event.target.value }))}
            className="w-full rounded-lg border border-border px-3 text-sm text-foreground"
            autoComplete="tel"
          />
        </label>
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground">
          <span>{t("drivers.vehiclePlate")}</span>
          <input
            maxLength={32}
            value={form.vehicle_plate}
            onChange={(event) => setForm((current) => ({ ...current, vehicle_plate: event.target.value }))}
            className="w-full rounded-lg border border-border px-3 text-sm text-foreground"
            autoComplete="off"
          />
        </label>
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground">
          <span>{t("waybill.driverId")}</span>
          <input
            maxLength={32}
            value={form.personal_id}
            onChange={(event) => setForm((current) => ({ ...current, personal_id: event.target.value }))}
            className="w-full rounded-lg border border-border px-3 text-sm text-foreground"
            autoComplete="off"
          />
        </label>
        <label className="space-y-1.5 text-xs font-medium text-muted-foreground">
          <span>{t("waybill.transport")}</span>
          <input
            maxLength={80}
            value={form.transport_type}
            onChange={(event) => setForm((current) => ({ ...current, transport_type: event.target.value }))}
            className="w-full rounded-lg border border-border px-3 text-sm text-foreground"
            autoComplete="off"
          />
        </label>
        <label className="flex items-center gap-2 self-end pb-2 text-xs font-medium text-muted-foreground">
          <input
            type="checkbox"
            checked={form.active}
            onChange={(event) => setForm((current) => ({ ...current, active: event.target.checked }))}
            className="accent-[hsl(var(--primary))]"
            data-testid="driver-active-checkbox"
          />
          {t("drivers.active")}
        </label>
        </div>
        <fieldset className="space-y-2">
          <legend className="text-xs font-medium text-muted-foreground">{t("drivers.workingDays")}</legend>
          <div className="flex flex-wrap gap-2">
            {WORK_DAYS.map((day) => (
              <label key={day.value} className={`inline-flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors ${
                form.working_days.includes(day.value) ? "border-processing/50 bg-processing/10 text-foreground" : "border-border bg-secondary/20 text-muted-foreground"
              }`}>
                <input
                  type="checkbox"
                  checked={form.working_days.includes(day.value)}
                  onChange={(event) => setForm((current) => ({
                    ...current,
                    working_days: event.target.checked
                      ? [...current.working_days, day.value].sort((a, b) => a - b)
                      : current.working_days.filter((value) => value !== day.value),
                  }))}
                  className="accent-[hsl(var(--primary))]"
                  data-testid={`driver-working-day-${day.value}`}
                />
                {day.label}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex justify-end gap-2">
          {editingId && (
            <Button type="button" variant="outline" size="icon" onClick={() => { setEditingId(null); setForm(EMPTY_DRIVER); }} aria-label={t("drivers.cancelEdit")}>
              <X className="h-4 w-4" />
            </Button>
          )}
          <Button type="submit" disabled={saving} data-testid="save-driver-button">
            {editingId ? <Save className="mr-2 h-4 w-4" /> : <Plus className="mr-2 h-4 w-4" />}
            {saving ? t("drivers.saving") : t(editingId ? "drivers.saveChanges" : "drivers.add")}
          </Button>
        </div>
      </form>

      {loading ? (
        <div className="h-36 animate-pulse rounded-xl bg-secondary" />
      ) : drivers.length ? (
        <ul className="space-y-3">
          {drivers.map((driver) => (
            <li key={driver.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4" data-testid={`driver-${driver.id}`}>
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-info/20 bg-info/10 text-info">
                <Truck className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-foreground">{driver.name}</p>
                <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
                  <Phone className="h-3.5 w-3.5" />{driver.phone}
                  {driver.vehicle_plate && <span>· {driver.vehicle_plate}</span>}
                </p>
              </div>
              <Button type="button" variant="outline" size="sm" onClick={() => editDriver(driver)} data-testid={`edit-driver-${driver.id}`}>
                <Pencil className="mr-1.5 h-3.5 w-3.5" />{t("drivers.edit")}
              </Button>
              <Button type="button" variant="outline" size="icon" onClick={() => removeDriver(driver.id)} aria-label={`${t("drivers.remove")} ${driver.name}`} data-testid={`remove-driver-${driver.id}`}>
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="rounded-xl border border-dashed border-border bg-card/50 px-6 py-12 text-center">
          <Truck className="mx-auto h-8 w-8 text-muted-foreground" />
          <p className="mt-3 text-sm text-muted-foreground">{t("drivers.empty")}</p>
        </div>
      )}

      <section className="space-y-5 rounded-xl border border-border bg-card p-5 sm:p-6" aria-label={t("drivers.dispatchCalendar")} data-testid="driver-dispatch-calendar">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-highlight">{t("drivers.dispatchCalendar")}</p>
            <h2 className="mt-1 flex items-center gap-2 text-lg font-semibold"><CalendarDays className="h-5 w-5 text-processing" />{t("drivers.weeklyDailyDispatch")}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{t("drivers.calendarDescription")}</p>
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" size="icon" onClick={() => changeWeek(-1)} aria-label={t("drivers.previousWeek")}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button type="button" variant="outline" size="icon" onClick={() => changeWeek(1)} aria-label={t("drivers.nextWeek")}>
              <ChevronRight className="h-4 w-4" />
            </Button>
            <Button type="button" variant={dispatchView === "day" ? "default" : "outline"} size="sm" onClick={() => setDispatchView("day")}>{t("drivers.dailyView")}</Button>
            <Button type="button" variant={dispatchView === "week" ? "default" : "outline"} size="sm" onClick={() => setDispatchView("week")}>{t("drivers.weeklyView")}</Button>
          </div>
        </div>

        {dispatchView === "week" ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7" data-testid="weekly-dispatch-view">
            {weekDates.map((date) => (
              <button
                type="button"
                key={date}
                onClick={() => { selectDispatchDay(date); setDispatchView("day"); }}
                className={`min-h-32 rounded-lg border p-3 text-left transition-colors ${
                  selectedDate === date ? "border-processing/50 bg-processing/10" : "border-border bg-secondary/20 hover:bg-secondary/50"
                }`}
                data-testid={`dispatch-day-${date}`}
              >
                <span className="block text-[11px] font-semibold uppercase text-muted-foreground">{georgianWeekday(date)}</span>
                <span className="mt-1 block font-mono text-lg font-semibold">{formatDay(date, { day: "numeric", month: "short" })}</span>
                <span className="mt-2 block text-xs text-muted-foreground">{routesForDate(date).length} {t("drivers.routesCount")}</span>
                {routesForDate(date).slice(0, 2).map((route) => (
                  <span key={route.id} className="mt-1 block truncate rounded bg-background/70 px-1.5 py-1 text-[10px] text-foreground">
                    {route.driver_name} · {routeLabel(route)}
                  </span>
                ))}
              </button>
            ))}
          </div>
        ) : (
          <div className="space-y-4" data-testid="daily-dispatch-view">
            <label className="block max-w-xs space-y-1 text-xs font-medium text-muted-foreground">
              <span>{t("drivers.selectDate")}</span>
              <input
                type="date"
                value={selectedDate}
                onChange={(event) => selectDispatchDay(event.target.value)}
                className="block w-full rounded-lg border border-border px-3 text-sm text-foreground"
                data-testid="driver-calendar-date"
              />
            </label>
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <div className="rounded-lg border border-border bg-secondary/20 p-4">
                <h3 className="mb-3 text-sm font-semibold">
                  {formatDay(selectedDate, { weekday: "long", month: "long", day: "numeric" })}
                </h3>
                {renderAssignedRoutes(selectedDate)}
                <form onSubmit={createCalendarExternalOrder} className="mt-4 space-y-3 border-t border-border pt-4" data-testid="calendar-external-order-form">
                  <h4 className="text-sm font-semibold">{t("drivers.addExternalStop")}</h4>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Input required maxLength={160} placeholder={t("orders.customerName")} aria-label={t("orders.customerName")} value={manualOrder.customer_name} onChange={(event) => setManualOrder((current) => ({ ...current, customer_name: event.target.value }))} />
                    <Input type="tel" maxLength={40} placeholder={t("orders.customerPhone")} aria-label={t("orders.customerPhone")} value={manualOrder.customer_phone} onChange={(event) => setManualOrder((current) => ({ ...current, customer_phone: event.target.value }))} />
                    <Input required maxLength={200} placeholder={t("orders.itemName")} aria-label={t("orders.itemName")} value={manualOrder.item_name} onChange={(event) => setManualOrder((current) => ({ ...current, item_name: event.target.value }))} />
                    <Input required type="number" min="1" max="100000" step="1" placeholder={t("orders.quantity")} aria-label={t("orders.quantity")} value={manualOrder.quantity} onChange={(event) => setManualOrder((current) => ({ ...current, quantity: event.target.value }))} />
                    <Input required type="number" min="0" step="0.01" placeholder={t("orders.unitPrice")} aria-label={t("orders.unitPrice")} value={manualOrder.unit_price} onChange={(event) => setManualOrder((current) => ({ ...current, unit_price: event.target.value }))} />
                  </div>
                  <AddressMapPicker value={manualOrder} onChange={(location) => setManualOrder((current) => ({ ...current, ...location }))} />
                  <Button type="submit" variant="outline" className="w-full" disabled={creatingExternalOrder} data-testid="add-calendar-external-order-button">
                    <Plus className="mr-2 h-4 w-4" />{creatingExternalOrder ? t("drivers.addingExternalStop") : t("drivers.addExternalStop")}
                  </Button>
                </form>
              </div>
              <form onSubmit={scheduleRoute} className="space-y-3 rounded-lg border border-border bg-secondary/20 p-4" data-testid="schedule-driver-route-form">
                <h3 className="text-sm font-semibold">{t("drivers.optimizeAndAssign")}</h3>
                <label className="block space-y-1 text-xs text-muted-foreground">
                  <span>{t("route.selectDriver")}</span>
                  <select required value={selectedDriverId} onChange={(event) => selectDispatchDriver(event.target.value)} className="w-full rounded-lg border border-border px-3 text-sm text-foreground">
                    {eligibleDrivers.length ? <option value="">{t("route.chooseDriver")}</option> : <option value="">{t("drivers.noEligibleDrivers")}</option>}
                    {eligibleDrivers.map((driver) => <option key={driver.id} value={driver.id}>{driver.name}</option>)}
                  </select>
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="block space-y-1 text-xs text-muted-foreground">
                    <span>{t("drivers.selectDate")}</span>
                    <input required type="date" value={selectedDate} onChange={(event) => selectDispatchDay(event.target.value)} className="w-full rounded-lg border border-border px-3 text-sm text-foreground" />
                  </label>
                  <label className="block space-y-1 text-xs text-muted-foreground">
                    <span>{t("drivers.routeTime")}</span>
                    <input required type="time" value={scheduleTime} onChange={(event) => setScheduleTime(event.target.value)} className="w-full rounded-lg border border-border px-3 text-sm text-foreground" />
                  </label>
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-semibold">{t("drivers.deliveriesForRoute")}</h4>
                    <span className="font-mono text-xs text-muted-foreground">{selectedOrderIds.length}/{selectableOrders.length}</span>
                  </div>
                  {selectableOrders.length ? (
                    <ul className="max-h-56 space-y-2 overflow-y-auto">
                      {selectableOrders.map((order) => (
                        <li key={order.id}>
                          <label className="flex cursor-pointer items-start gap-2 rounded-md border border-border bg-background/60 p-2 text-xs">
                            <input
                              type="checkbox"
                              checked={selectedOrderIds.includes(order.id)}
                              onChange={() => toggleOrderSelection(order.id)}
                              className="mt-0.5 accent-[hsl(var(--primary))]"
                              data-testid={`dispatch-order-${order.id}`}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="flex flex-wrap items-center gap-2 font-mono font-semibold">
                                {order.order_no}
                                {(order.external_order || order.is_external) && <span className="rounded-full border border-highlight/30 bg-highlight/10 px-1.5 py-0.5 font-sans text-[9px] text-highlight">{t("orders.externalBadge")}</span>}
                              </span>
                              <span className="mt-1 block truncate text-muted-foreground">{order.retailer_name} · {order.delivery_address}</span>
                            </span>
                          </label>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">{t("route.noUnassignedOrders")}</p>
                  )}
                </div>
                <Button type="submit" className="w-full" disabled={scheduling || !selectedDriverId || !selectedOrderIds.length} data-testid="assign-driver-route-button">
                  <Plus className="mr-2 h-4 w-4" />{scheduling ? t("drivers.optimizingRoute") : t("drivers.optimizeAndAssign")}
                </Button>
              </form>
            </div>
          </div>
        )}
      </section>

      <Dialog open={Boolean(dispatchLink)} onOpenChange={(open) => { if (!open) setDispatchLink(null); }}>
        <DialogContent className="border-border bg-card text-foreground">
          <DialogHeader>
            <DialogTitle>{t("drivers.dispatchLinkTitle")}</DialogTitle>
            <DialogDescription>{t("drivers.dispatchLinkDescription")}</DialogDescription>
          </DialogHeader>
          {dispatchLink && (
            <>
              <div className="flex items-center gap-2 rounded-lg border border-border bg-secondary/30 p-3">
                <Link2 className="h-4 w-4 shrink-0 text-highlight" />
                <a href={dispatchLink.url} target="_blank" rel="noreferrer" className="min-w-0 break-all text-xs text-info underline">
                  {dispatchLink.url}
                </a>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="shrink-0"
                  aria-label={t("drivers.copyLink")}
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(dispatchLink.url);
                      toast.success(t("route.linkCopied"));
                    } catch (error) {
                      console.error("Could not copy generated driver route link:", error);
                      toast.error(t("route.copyError"));
                    }
                  }}
                >
                  <Copy className="h-4 w-4" />
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                {dispatchLink.route.driver_name} · {dispatchLink.route.driver_phone} · {formatDay(toDateInputValue(new Date(dispatchLink.route.scheduled_at)), { dateStyle: "medium" })}
              </p>
              <DialogFooter className="gap-2 sm:gap-2">
                <Button asChild disabled={!smsPhone}>
                  <a href={smsUrl} data-testid="dispatch-link-sms">
                    <MessageSquareText className="mr-2 h-4 w-4" />{t("route.sendSMS")}
                  </a>
                </Button>
                <Button asChild variant="outline" disabled={!whatsappPhone}>
                  <a href={whatsappUrl} target="_blank" rel="noreferrer" data-testid="dispatch-link-whatsapp">
                    <MessageCircle className="mr-2 h-4 w-4" />{t("route.sendWhatsApp")}
                  </a>
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
