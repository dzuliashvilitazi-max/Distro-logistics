import { useEffect, useState } from "react";
import { API } from "@/lib/api";
import { cn } from "@/lib/utils";

const PALETTE = [
  ["#edf3ee", "#52785b"], ["#eef2f9", "#4b6a9b"], ["#f8f1e8", "#9b6a2f"],
  ["#f5ecf3", "#8a4f7d"], ["#e9f4f5", "#2f7f86"], ["#f7eeee", "#a3524f"],
];

const escapeXml = (value) => String(value).replace(/[<>&"']/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" }[c]));

// Category-specific placeholder: the same category always gets the same colour and label, never an unrelated photo.
function categoryPlaceholder(category) {
  const label = String(category || "").trim();
  const hash = Array.from(label).reduce((h, ch) => Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0, 2166136261);
  const [background, accent] = PALETTE[hash % PALETTE.length];
  const short = label.length > 22 ? `${label.slice(0, 21)}…` : label;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 240"><rect width="320" height="240" fill="${background}"/><circle cx="258" cy="50" r="44" fill="${accent}" opacity=".12"/><path d="M91 77h138l-12 126H103L91 77Z" fill="#fff" stroke="${accent}" stroke-width="6"/><path d="M91 77h138l-8 39H99L91 77Z" fill="${accent}" opacity=".45"/><path d="M138 147h44" stroke="${accent}" stroke-width="7" stroke-linecap="round"/>${short ? `<text x="160" y="226" text-anchor="middle" font-family="sans-serif" font-size="14" fill="${accent}">${escapeXml(short)}</text>` : ""}</svg>`;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

function resolveSource(image) {
  const value = String(image || "").trim();
  if (!value || /loremflickr\.com/i.test(value) || ["null", "none", "undefined"].includes(value.toLowerCase())) return "";
  return value.startsWith("/") ? `${API}${value}` : value;
}

export default function ProductImage({ image, name, category, alt = "", className = "", ...props }) {
  const placeholder = categoryPlaceholder(category);
  const source = resolveSource(image);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(!source);

  useEffect(() => {
    setFailed(false);
    setLoaded(!source);
  }, [source]);

  return (
    <img
      {...props}
      src={failed || !source ? placeholder : source}
      alt={alt || name || ""}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      className={cn("bg-secondary transition-opacity duration-300", loaded ? "opacity-100" : "opacity-0", className)}
      onLoad={() => setLoaded(true)}
      onError={() => { setFailed(true); setLoaded(true); }}
    />
  );
}
