import { useEffect, useState } from "react";

let deferredPrompt = null;
const listeners = new Set();
const notify = () => listeners.forEach((fn) => fn());

export const isStandalone = () =>
  typeof window !== "undefined"
  && (window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true);

export function registerServiceWorker() {
  if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    notify();
  });

  // Service worker is production-only so dev hot reload is never served stale files.
  if (import.meta.env.PROD) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch((error) => {
        console.error("Service worker registration failed:", error);
      });
    });
  }
}

export function usePwaInstall() {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((n) => n + 1);
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, []);

  const isIos = /iphone|ipad|ipod/i.test(window.navigator.userAgent);
  const installed = isStandalone();
  const canPrompt = !!deferredPrompt;
  // iOS Safari has no install prompt API, so it gets manual "Add to Home Screen" instructions.
  const showInstall = !installed && (canPrompt || isIos);

  const install = async () => {
    if (!deferredPrompt) return "manual";
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    deferredPrompt = null;
    notify();
    return outcome;
  };

  return { showInstall, canPrompt, isIos, install };
}
