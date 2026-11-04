export function googleNavigationUrl(lat, lon) {
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(`${lat},${lon}`)}&travelmode=driving`;
}

export function wazeNavigationUrl(lat, lon) {
  return `https://waze.com/ul?ll=${encodeURIComponent(`${lat},${lon}`)}&navigate=yes`;
}

export function launchYandexNavigation(lat, lon) {
  const fallbackUrl = `https://yandex.com/maps/?rtext=~${encodeURIComponent(`${lat},${lon}`)}`;
  const deepLink = `yandexnavi://build_route_on_map?lat_to=${encodeURIComponent(lat)}&lon_to=${encodeURIComponent(lon)}`;
  const handleVisibilityChange = () => {
    if (document.visibilityState === "hidden") window.clearTimeout(fallbackTimer);
  };
  const fallbackTimer = window.setTimeout(() => {
    document.removeEventListener("visibilitychange", handleVisibilityChange);
    if (document.visibilityState === "visible") window.location.assign(fallbackUrl);
  }, 1200);
  document.addEventListener("visibilitychange", handleVisibilityChange, { once: true });
  window.location.href = deepLink;
}
