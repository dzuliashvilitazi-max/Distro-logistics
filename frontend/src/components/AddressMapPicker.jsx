import { useEffect, useRef, useState } from "react";
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import { Loader2, Search } from "lucide-react";
import { api, formatApiError } from "@/lib/api";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

import "leaflet/dist/leaflet.css";

const DEFAULT_CENTER = { lat: 41.7151, lng: 44.8271 };
const PIN_ICON = L.divIcon({
  className: "address-picker-pin",
  html: "<span style=\"display:block;width:24px;height:24px;border:3px solid white;border-radius:50% 50% 50% 0;background:#e11d48;box-shadow:0 2px 6px #0006;transform:rotate(-45deg)\"></span>",
  iconSize: [24, 24],
  iconAnchor: [12, 21],
});

function MapCenter({ center }) {
  const map = useMap();
  useEffect(() => {
    map.setView([center.lat, center.lng], Math.max(map.getZoom(), 16));
  }, [center, map]);
  return null;
}

function MapClick({ onPick, disabled }) {
  useMapEvents({ click: ({ latlng }) => { if (!disabled) onPick(latlng.lat, latlng.lng); } });
  return null;
}

export default function AddressMapPicker({ value, onChange, disabled = false }) {
  const { t } = useI18n();
  const hasCoordinates = Number.isFinite(value?.lat) && Number.isFinite(value?.lng);
  const [center, setCenter] = useState(hasCoordinates ? { lat: value.lat, lng: value.lng } : DEFAULT_CENTER);
  const [query, setQuery] = useState(value?.label || value?.address || "");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [resolving, setResolving] = useState(false);
  const searchSequence = useRef(0);
  const selectedLabel = useRef("");

  useEffect(() => {
    if (Number.isFinite(value?.lat) && Number.isFinite(value?.lng)) {
      setCenter({ lat: value.lat, lng: value.lng });
    }
    const label = value?.label || value?.address;
    if (label) setQuery(label);
  }, [value?.lat, value?.lng, value?.address, value?.label]);

  const choosePin = async (lat, lng) => {
    const point = { lat: Number(lat), lng: Number(lng) };
    searchSequence.current += 1;
    selectedLabel.current = "";
    setCenter(point);
    setQuery("");
    setResults([]);
    setResolving(true);
    onChange({ ...value, ...point, address: "", city: "" });
    try {
      const { data } = await api.get("/addresses/reverse", { params: point });
      const label = data.label || data.address || "";
      selectedLabel.current = label;
      setQuery(label);
      onChange(data);
    } catch (error) {
      toast.error(formatApiError(error.response?.data?.detail) || t("address.reverseError"));
    } finally {
      setResolving(false);
    }
  };

  const selectSuggestion = (suggestion) => {
    const point = { lat: Number(suggestion.lat), lng: Number(suggestion.lng) };
    const label = suggestion.label || suggestion.address || "";
    searchSequence.current += 1;
    selectedLabel.current = label;
    setSearching(false);
    setResults([]);
    setCenter(point);
    setQuery(label);
    onChange({ ...value, ...suggestion, ...point, label });
  };

  const searchAddress = async (searchQuery = query) => {
    const normalizedQuery = searchQuery.trim();
    if (normalizedQuery.length < 3 || disabled) return;
    const sequence = ++searchSequence.current;
    setSearching(true);
    try {
      const { data } = await api.get("/addresses/search", { params: { query: normalizedQuery } });
      if (sequence !== searchSequence.current) return;
      setResults(data);
      if (!data.length) toast.message(t("address.noResults"));
    } catch (error) {
      if (sequence !== searchSequence.current) return;
      toast.error(formatApiError(error.response?.data?.detail) || t("address.searchError"));
    } finally {
      if (sequence === searchSequence.current) setSearching(false);
    }
  };

  useEffect(() => {
    if (selectedLabel.current && query.trim() === selectedLabel.current) {
      selectedLabel.current = "";
      searchSequence.current += 1;
      setSearching(false);
      setResults([]);
      return undefined;
    }
    if (disabled || query.trim().length < 3) {
      searchSequence.current += 1;
      setSearching(false);
      setResults([]);
      return undefined;
    }
    const timer = window.setTimeout(() => { void searchAddress(query); }, 400);
    return () => window.clearTimeout(timer);
  }, [query, disabled]);

  return (
    <div className="min-w-0 max-w-full space-y-3" data-testid="address-map-picker">
      <div className="flex gap-2">
        <div className="min-w-0 flex-1">
          <Label htmlFor="address-map-search">{t("address.search")}</Label>
          <Input
            id="address-map-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDownCapture={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                event.stopPropagation();
                void searchAddress();
              }
            }}
            disabled={disabled}
            className="mt-1"
            data-testid="address-map-search-input"
          />
        </div>
        <Button type="button" variant="outline" className="mt-6 shrink-0" onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          void searchAddress();
        }} disabled={disabled || searching || query.trim().length < 3} aria-label={t("address.search")} data-testid="address-map-search-submit">
          {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
        </Button>
      </div>
      {results.length > 0 && (
        <div className="max-h-36 overflow-y-auto rounded-md border border-border bg-popover" role="listbox" aria-label={t("address.searchResults")}>
          {results.map((result, index) => (
            <button key={`${result.lat}:${result.lng}:${index}`} type="button" className="block w-full break-words border-b border-border px-3 py-2 text-left text-xs last:border-0 hover:bg-secondary" onMouseDown={(event) => event.preventDefault()} onClick={() => selectSuggestion(result)}>
              {result.label || [result.address, result.city].filter(Boolean).join(", ")}
            </button>
          ))}
        </div>
      )}
      <div className="relative min-w-0 max-w-full overflow-hidden rounded-lg border border-border">
        <MapContainer center={[center.lat, center.lng]} zoom={15} scrollWheelZoom className="h-[320px] w-full max-w-full sm:h-[390px]" data-testid="address-map">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <MapCenter center={center} />
          <MapClick onPick={choosePin} disabled={disabled} />
          {hasCoordinates && (
            <Marker
              position={[center.lat, center.lng]}
              icon={PIN_ICON}
              draggable={!disabled}
              eventHandlers={{ dragend: (event) => {
                const point = event.target.getLatLng();
                choosePin(point.lat, point.lng);
              } }}
            />
          )}
        </MapContainer>
        {resolving && <span className="absolute left-3 top-3 inline-flex items-center gap-2 rounded-md bg-background/95 px-2.5 py-1.5 text-xs shadow" role="status"><Loader2 className="h-3.5 w-3.5 animate-spin" />{t("address.resolving")}</span>}
      </div>
      {value?.address && <p className="text-sm font-medium" data-testid="address-map-resolved-address">{value.address}{value.city ? `, ${value.city}` : ""}</p>}
    </div>
  );
}