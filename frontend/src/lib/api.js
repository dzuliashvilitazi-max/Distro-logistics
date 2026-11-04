import axios from "axios";

const viteBackendUrl = import.meta.env.VITE_BACKEND_URL?.trim();
const legacyBackendUrl = import.meta.env.REACT_APP_BACKEND_URL?.trim();
const backendPort = import.meta.env.VITE_BACKEND_PORT?.trim() || "8000";
const browserLocation = typeof window === "undefined" ? null : window.location;
const isLocalFrontend = browserLocation
  && ["localhost", "127.0.0.1"].includes(browserLocation.hostname);
const defaultBackendUrl = !browserLocation
  ? `http://127.0.0.1:${backendPort}`
  : isLocalFrontend
    ? `${browserLocation.protocol}//${browserLocation.hostname}:${backendPort}`
    : browserLocation.origin;
const backendRoot = (viteBackendUrl || (isLocalFrontend ? defaultBackendUrl : legacyBackendUrl || defaultBackendUrl))
  .replace(/\/+$/, "")
  .replace(/\/api$/i, "");
export const API = `${backendRoot}/api`;

export const api = axios.create({ baseURL: API, timeout: 60000 });

// Readable message for any failed request, including network errors and timeouts.
export function requestErrorMessage(err) {
  if (err?.response) {
    const detail = err.response.data?.detail;
    if (detail != null) return formatApiError(detail);
    return `Server error (${err.response.status}). Please try again.`;
  }
  if (err?.code === "ECONNABORTED") return "The server took too long to respond. Please try again.";
  if (err?.request) return "Cannot reach the server. Check your connection and try again.";
  return err?.message || "Something went wrong. Please try again.";
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("distro_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("distro_token");
  if (!token) return config;
  try {
    const encodedPayload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/").padEnd(
      Math.ceil(token.split(".")[1].length / 4) * 4, "=",
    );
    const payload = JSON.parse(atob(encodedPayload));
    if (payload.app_role !== "supplier") return config;

    const path = new URL(config.url || "", config.baseURL || API).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/supplier/warehouses" || path.startsWith("/supplier/staff")
      || path.startsWith("/auth/") || path.includes("/shared/")) return config;

    const selectedWarehouse = payload.assigned_branch_id
      || localStorage.getItem(`distro_supplier_warehouse:${payload.supplier_id || payload.sub}`);
    if (selectedWarehouse) {
      config.params = { ...config.params, warehouse_id: selectedWarehouse };
    }
  } catch (error) {
    console.error("Could not read supplier branch from the access token:", error);
  }
  return config;
});

// Absolute URL of a user's uploaded logo, or null so callers can render a fallback instead of an empty src.
export function logoSrc(entity) {
  return entity?.logo_url ? `${API}${entity.logo_url}` : null;
}

export function formatApiError(detail) {
  if (detail == null) return "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e))).join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}

export function tierPrice(product, qty) {
  let price = product.price_per_unit;
  const tiers = [...(product.tier_pricing || [])].sort((a, b) => a.min_qty - b.min_qty);
  for (const t of tiers) if (qty >= t.min_qty) price = t.price;
  return price;
}
