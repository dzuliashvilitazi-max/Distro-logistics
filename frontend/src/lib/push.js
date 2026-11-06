import { api } from "@/lib/api";

let preparedPushContextPromise;

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

/** Prepare registration, server key, and any existing subscription before a user clicks. */
export function preparePushSubscription() {
  if (!supported()) return Promise.resolve(null);
  if (!preparedPushContextPromise) {
    preparedPushContextPromise = Promise.all([
      registration(),
      api.get("/push/public-key"),
    ]).then(async ([reg, { data }]) => {
      if (!reg) return null;
      const applicationServerKey = urlBase64ToUint8Array(data.public_key);
      let subscription = await reg.pushManager.getSubscription();
      if (subscription && !applicationServerKeyMatches(subscription, applicationServerKey)) {
        console.warn("Push VAPID key changed; rotating browser subscription");
        await api.post("/push/unsubscribe", { endpoint: subscription.endpoint });
        await subscription.unsubscribe();
        subscription = null;
      }
      return { reg, applicationServerKey, subscription };
    }).catch((error) => {
      preparedPushContextPromise = null;
      throw error;
    });
  }
  return preparedPushContextPromise;
}

function savePushSubscription(subscription) {
  const payload = subscription.toJSON();
  const hasEndpoint = Boolean(payload.endpoint);
  const hasP256dh = Boolean(payload.keys?.p256dh);
  const hasAuth = Boolean(payload.keys?.auth);
  console.info("Push subscription prepared", { hasEndpoint, hasP256dh, hasAuth });
  if (!hasEndpoint || !hasP256dh || !hasAuth) {
    throw new Error("Push subscription is missing its endpoint or encryption keys.");
  }
  return api.post("/push/subscribe", payload).then(() => {
      console.info("Push subscription registered with backend");
      return true;
    }).catch((error) => {
    console.error("Push subscription registration failed", {
      status: error.response?.status || null,
      error: error.name,
    });
      throw error;
    });
}

/** Subscribes on a user gesture and binds this browser to the signed-in user. */
export function subscribeToPush() {
  if (!supported() || Notification.permission !== "granted") return Promise.resolve(false);
  return preparePushSubscription().then((context) => {
    if (!context) return false;
    const subscriptionPromise = context.subscription
      ? Promise.resolve(context.subscription)
      : context.reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: context.applicationServerKey,
      });
    return subscriptionPromise.then((subscription) => {
      context.subscription = subscription;
      return savePushSubscription(subscription);
    });
  });
}

/** Rebind an existing subscription after login without creating one outside a click. */
export function syncExistingPushSubscription() {
  if (!supported() || Notification.permission !== "granted") return Promise.resolve(false);
  return preparePushSubscription().then((context) => {
    if (!context?.subscription) return false;
    return savePushSubscription(context.subscription);
  });
}

/** Asks for permission when it has not been decided yet, then subscribes. Returns the permission state. */
export function enablePush() {
  if (!supported()) return Promise.resolve("unsupported");
  let permissionRequest;
  try {
    permissionRequest = Notification.permission === "default"
      ? Notification.requestPermission()
      : Promise.resolve(Notification.permission);
  } catch (error) {
    return Promise.reject(error);
  }
  return permissionRequest.then((permission) => {
    if (permission !== "granted") return permission;
    return subscribeToPush().then(() => permission);
  });
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
