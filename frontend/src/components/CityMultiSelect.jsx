import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search, X } from "lucide-react";
import { useI18n } from "@/context/I18nContext";
import { ALL_CITIES, isAllCities, canonCity, searchCities } from "@/lib/cities";
import { cn } from "@/lib/utils";

// Searchable dropdown over GEORGIAN_CITIES. Multi mode shows selections as removable tags;
// `single` mode keeps at most one city (onChange receives [city] or []).
export function CityMultiSelect({
  value = [], onChange, idPrefix = "city", single = false, allowAll = !single, placeholder, className,
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef(null);

  const all = allowAll && isAllCities(value);
  const selected = useMemo(
    () => (all ? [] : [...new Set(value.map(canonCity).filter(Boolean))]),
    [value, all],
  );
  const options = useMemo(() => searchCities(query), [query]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const toggle = (city) => {
    if (single) {
      onChange(selected.includes(city) ? [] : [city]);
      setOpen(false);
      setQuery("");
      return;
    }
    onChange(selected.includes(city) ? selected.filter((c) => c !== city) : [...selected, city]);
  };
  const remove = (city) => onChange(selected.filter((c) => c !== city));
  const toggleAll = () => onChange(all ? [] : [ALL_CITIES]);

  const tags = all ? [t("prof.allCities")] : selected;
  const searchLabel = t("common.search");

  return (
    <div ref={rootRef} className={cn("relative", className)} data-testid={`${idPrefix}-multiselect`}>
      <div
        role="combobox"
        aria-expanded={open}
        tabIndex={0}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen((o) => !o); }
          if (e.key === "Escape") setOpen(false);
        }}
        className="flex min-h-10 w-full cursor-pointer items-center justify-between gap-2 rounded-md border border-input bg-background px-3 py-1.5 text-sm"
      >
        <div className="flex flex-1 flex-wrap items-center gap-1">
          {tags.length === 0 && <span className="text-muted-foreground">{placeholder || t("prof.selectCities")}</span>}
          {tags.map((city) => (
            <span key={city} className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-xs font-medium" data-testid={`${idPrefix}-tag-${city}`}>
              {city}
              {!all && (
                <button type="button" aria-label={`remove ${city}`} className="opacity-60 hover:opacity-100"
                  onClick={(e) => { e.stopPropagation(); remove(city); }}>
                  <X className="h-3 w-3" />
                </button>
              )}
            </span>
          ))}
        </div>
        <ChevronDown className={cn("h-4 w-4 shrink-0 opacity-60 transition", open && "rotate-180")} />
      </div>

      {open && (
        <div className="absolute z-30 mt-1 w-full rounded-md border border-border bg-popover p-2 shadow-md">
          <div className="relative mb-2">
            <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setOpen(false);
                if (e.key === "Enter") { e.preventDefault(); if (options.length === 1 && !all) toggle(options[0]); }
              }}
              placeholder={searchLabel === "common.search" ? "Search…" : searchLabel}
              className="h-9 w-full rounded-md border border-input bg-background pl-8 pr-2 text-sm outline-none"
              data-testid={`${idPrefix}-search`}
            />
          </div>
          <ul className="max-h-56 overflow-auto" role="listbox" aria-multiselectable={!single}>
            {allowAll && !query && (
              <li role="option" aria-selected={all} onClick={toggleAll} data-testid={`${idPrefix}-all`}
                className="flex cursor-pointer items-center justify-between rounded px-2 py-1.5 text-sm font-medium hover:bg-accent">
                {t("prof.allCities")}{all && <Check className="h-4 w-4" />}
              </li>
            )}
            {options.map((city) => {
              const on = all || selected.includes(city);
              return (
                <li key={city} role="option" aria-selected={on} onClick={() => !all && toggle(city)} data-testid={`${idPrefix}-${city}`}
                  className={cn("flex items-center justify-between rounded px-2 py-1.5 text-sm hover:bg-accent", all ? "cursor-not-allowed opacity-50" : "cursor-pointer")}>
                  {city}{on && <Check className="h-4 w-4" />}
                </li>
              );
            })}
            {options.length === 0 && <li className="px-2 py-2 text-sm text-muted-foreground">—</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
