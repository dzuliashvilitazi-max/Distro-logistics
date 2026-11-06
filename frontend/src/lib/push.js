import { api } from "@/lib/api";

const supported = () =>
  typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

function urlBase64ToUint8Array(value) {
  const padded = value + "=".repeat((4 - (value.length % 4)) % 4);
  const raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

function applicationServerKeyMatches(subscription, expectedKey) {
  const currentKey = subscription?.options?.applicationServerKey;
  if (!currentKey) return true;
  const currentBytes = currentKey instanceof ArrayBuffer
    ? new Uint8Array(currentKey)
    : ArrayBuffer.isView(currentKey)
      ? new Uint8Array(currentKey.buffer, currentKey.byteOffset, currentKey.byteLength)
      : null;
  return Boolean(currentBytes)
    && currentBytes.length === expectedKey.length
    && currentBytes.every((value, index) => value === expectedKey[index]);
}

// The service worker is only registered in production builds (see lib/pwa.js), so push works there.
async function registration() {
  const existing = await navigator.serviceWorker.getRegistration();
  if (existing) return existing.active ? existing : navigator.serviceWorker.ready;
  if (!import.meta.env.PROD) return null;
  await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  return navigator.serviceWorker.ready;
}

/** Subscribes this browser and binds it to the signed-in user. Safe to call repeatedly. */
export async function subscribeToPush() {
  if (!supported() || Notification.permission !== "granted") return false;
  const reg = await registration();
  if (!reg) return false;
  const { data } = await api.get("/push/public-key");
  const applicationServerKey = urlBase64ToUint8Array(data.public_key);
  let subscription = await reg.pushManager.getSubscription();
  if (subscription && !applicationServerKeyMatches(subscription, applicationServerKey)) {
    console.warn("Push VAPID key changed; rotating browser subscription");
    await api.post("/push/unsubscribe", { endpoint: subscription.endpoint });
    await subscription.unsubscribe();
    subscription = null;
  }
  subscription = subscription || await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey,
    });
  const payload = subscription.toJSON();
  const hasEndpoint = Boolean(payload.endpoint);
  const hasP256dh = Boolean(payload.keys?.p256dh);
  const hasAuth = Boolean(payload.keys?.auth);
  console.info("Push subscription prepared", { hasEndpoint, hasP256dh, hasAuth });
  if (!hasEndpoint || !hasP256dh || !hasAuth) {
    throw new Error("Push subscription is missing its endpoint or encryption keys.");
  }
  try {
    await api.post("/push/subscribe", payload);
    console.info("Push subscription registered with backend");
  } catch (error) {
    console.error("Push subscription registration failed", {
      status: error.response?.status || null,
      error: error.name,
    });
    throw error;
  }
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
