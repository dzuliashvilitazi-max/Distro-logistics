import { api } from "@/lib/api";

const supported = () =>
  typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

function urlBase64ToUint8Array(value) {
  const padded = value + "=".repeat((4 - (value.length % 4)) % 4);
  const raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

// The service worker is only registered in production builds (see lib/pwa.js), so push works there.
async function registration() {
  const existing = await navigator.serviceWorker.getRegistration();
  if (existing) return existing.active ? existing : navigator.serviceWorker.ready;
  if (!import.meta.env.PROD) return null;
  await navigator.serviceWorker.register("/sw.js");
  return navigator.serviceWorker.ready;
}

/** Subscribes this browser and binds it to the signed-in user. Safe to call repeatedly. */
export async function subscribeToPush() {
  if (!supported() || Notification.permission !== "granted") return false;
  const reg = await registration();
  if (!reg) return false;
  const { data } = await api.get("/push/public-key");
  const subscription = (await reg.pushManager.getSubscription())
    || await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(data.public_key),
    });
  await api.post("/push/subscribe", subscription.toJSON());
  return true;
}

/** Asks for permission when it has not been decided yet, then subscribes. Returns the permission state. */
export async function enablePush() {
  if (!supported()) return "unsupported";
  const permission = Notification.permission === "default"
    ? await Notification.requestPermission()
    : Notification.permission;
  if (permission === "granted") await subscribeToPush();
  return permission;
}

/** Called on logout so the next person on this device does not receive the previous user's pushes. */
export async function unsubscribeFromPush(token) {
  if (!supported()) return;
  try {
    const reg = await navigator.serviceWorker.getRegistration();
    const subscription = reg && await reg.pushManager.getSubscription();
    if (!subscription) return;
    // The session token is cleared right after logout, so it is passed explicitly.
    await api.post("/push/unsubscribe", { endpoint: subscription.endpoint }, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    await subscription.unsubscribe();
  } catch (error) {
    console.warn("Could not remove push subscription:", error);
  }
}
