import { useEffect, useState } from "react";

let deferredPrompt = null;
const listeners = new Set();
const notify = () => listeners.forEach((fn) => fn());

const PWA_LAUNCH_KEY = "distro-pwa-launch";

export function checkStandalone() {
  if (typeof window === "undefined") return false;

  const launchedFromManifest = new URLSearchParams(window.location.search).get("source") === "pwa";
  if (launchedFromManifest) {
    try {
      window.sessionStorage.setItem(PWA_LAUNCH_KEY, "true");
    } catch (error) {
      console.warn("Could not persist PWA launch state:", error);
    }
  }

  let manifestLaunch = launchedFromManifest;
  if (!manifestLaunch) {
    try {
      manifestLaunch = window.sessionStorage.getItem(PWA_LAUNCH_KEY) === "true";
    } catch (error) {
      console.warn("Could not read PWA launch state:", error);
    }
  }

  const displayModes = ["standalone", "fullscreen", "minimal-ui"];
  const displayModeStandalone = displayModes.some((mode) => {
    try {
      return window.matchMedia(`(display-mode: ${mode})`).matches;
    } catch {
      return false;
    }
  });

  return window.navigator.standalone === true || displayModeStandalone || manifestLaunch;
}

export const isStandalone = checkStandalone;

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

  const isIos = /iphone|ipad|ipod/i.test(window.navigator.userAgent)
    || (window.navigator.platform === "MacIntel" && window.navigator.maxTouchPoints > 1);
  const installed = checkStandalone();
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
