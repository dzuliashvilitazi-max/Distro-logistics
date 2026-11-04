import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/context/I18nContext";
import { loadGoogleMapsApi } from "@/lib/googleMaps";

const FALLBACK_CENTER = { lat: 41.7151, lng: 44.8271 };
const DARK_MAP_STYLE = [
  { elementType: "geometry", stylers: [{ color: "#1b1f25" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#aeb6c2" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#111317" }] },
  { featureType: "administrative", elementType: "geometry.stroke", stylers: [{ color: "#353a43" }] },
  { featureType: "landscape", elementType: "geometry", stylers: [{ color: "#15181d" }] },
  { featureType: "poi", elementType: "geometry", stylers: [{ color: "#20252c" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#303640" }] },
  { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#252a32" }] },
  { featureType: "transit", elementType: "geometry", stylers: [{ color: "#252a32" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#101317" }] },
];

export default function GoogleTrafficMap({ route, selectedStop, onLoadError, onSelectStop }) {
  const { t } = useI18n();
  const mapElement = useRef(null);
  const map = useRef(null);
  const trafficLayer = useRef(null);
  const routeOverlays = useRef([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadGoogleMapsApi().then((google) => {
      if (cancelled || !mapElement.current) return;

      const instance = new google.maps.Map(mapElement.current, {
        center: FALLBACK_CENTER,
        zoom: 7,
        backgroundColor: "#111317",
        styles: DARK_MAP_STYLE,
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: false,
      });
      const liveTraffic = new google.maps.TrafficLayer();
      liveTraffic.setMap(instance);
      map.current = instance;
      trafficLayer.current = liveTraffic;
      setReady(true);
    }).catch(onLoadError);

    return () => {
      cancelled = true;
      routeOverlays.current.forEach((overlay) => overlay.setMap(null));
      routeOverlays.current = [];
      trafficLayer.current?.setMap(null);
      trafficLayer.current = null;
      map.current = null;
    };
  }, [onLoadError]);

  useEffect(() => {
    if (!ready || !map.current || !route) return;
    const google = window.google;
    routeOverlays.current.forEach((overlay) => overlay.setMap(null));
    routeOverlays.current = [];

    if (route.geometry?.length) {
      const line = new google.maps.Polyline({
        path: route.geometry.map(([lon, lat]) => ({ lat, lng: lon })),
        geodesic: true,
        strokeColor: "#e5b94c",
        strokeOpacity: 0.95,
        strokeWeight: 5,
        map: map.current,
      });
      routeOverlays.current.push(line);

      const bounds = new google.maps.LatLngBounds();
      route.geometry.forEach(([lon, lat]) => bounds.extend({ lat, lng: lon }));
      map.current.fitBounds(bounds, 40);
    }

    const markers = [
      { ...route.origin, label: "S", color: "#7898c5" },
      ...route.stops.map((stop) => ({ ...stop, label: String(stop.sequence), color: "#e5b94c" })),
    ].map((point) => {
      const marker = new google.maps.Marker({
        map: map.current,
        position: { lat: point.lat, lng: point.lon },
        label: { text: point.label, color: "#111317", fontWeight: "700" },
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          fillColor: point.color,
          fillOpacity: 1,
          strokeColor: "#111317",
          strokeWeight: 2,
          scale: 16,
        },
        title: point.order_no || t("route.startPoint"),
      });
      if (point.order_id) {
        marker.addListener("click", () => onSelectStop(point.order_id));
      }
      return marker;
    });
    routeOverlays.current.push(...markers);
  }, [ready, route, t, onSelectStop]);

  useEffect(() => {
    if (!ready || !map.current || !selectedStop) return;
    const stop = route?.stops.find((item) => item.order_id === selectedStop);
    if (stop) {
      map.current.panTo({ lat: stop.lat, lng: stop.lon });
      map.current.setZoom(Math.max(map.current.getZoom() || 0, 14));
    }
  }, [ready, route, selectedStop]);

  return (
    <div className="relative">
      <div ref={mapElement} className="h-[420px] w-full rounded-lg sm:h-[560px]" data-testid="delivery-route-map" />
      {ready && (
        <>
          <div className="absolute left-3 top-3 inline-flex items-center gap-2 rounded-lg border border-delivered/30 bg-industrial-base/90 px-3 py-2 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-foreground shadow-lg">
            <span className="h-2 w-2 animate-pulse rounded-full bg-delivered" />
            {t("route.liveTraffic")}
          </div>
          <div className="absolute bottom-3 left-3 flex flex-wrap gap-x-3 gap-y-1 rounded-lg border border-border bg-industrial-base/90 px-3 py-2 text-[10px] text-muted-foreground shadow-lg" aria-label={t("route.trafficLegend")}>
            <span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-emerald-500" />{t("route.trafficClear")}</span>
            <span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-yellow-400" />{t("route.trafficModerate")}</span>
            <span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-orange-500" />{t("route.trafficHeavy")}</span>
            <span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-red-600" />{t("route.trafficSevere")}</span>
          </div>
        </>
      )}
    </div>
  );
}
