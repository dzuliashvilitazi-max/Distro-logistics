let googleMapsPromise;

export const isGoogleMapsConfigured = Boolean(import.meta.env.VITE_GOOGLE_MAPS_API_KEY?.trim());

export function loadGoogleMapsApi() {
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY?.trim();
  if (!apiKey) return Promise.reject(new Error("VITE_GOOGLE_MAPS_API_KEY is not configured."));
  if (window.google?.maps?.DirectionsService) return Promise.resolve(window.google);
  if (googleMapsPromise) return googleMapsPromise;

  googleMapsPromise = new Promise((resolve, reject) => {
    const callbackName = "__distroGoogleMapsReady";
    const script = document.createElement("script");
    let timeoutId;

    const cleanup = () => {
      window.clearTimeout(timeoutId);
      delete window[callbackName];
      script.onerror = null;
    };
    const fail = (error) => {
      cleanup();
      googleMapsPromise = null;
      reject(error);
    };

    window[callbackName] = () => {
      cleanup();
      resolve(window.google);
    };
    script.async = true;
    script.defer = true;
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&callback=${callbackName}&loading=async&v=weekly`;
    script.onerror = () => fail(new Error("Google Maps JavaScript API could not be loaded."));
    timeoutId = window.setTimeout(() => fail(new Error("Google Maps JavaScript API timed out.")), 15000);
    document.head.appendChild(script);
  });

  return googleMapsPromise;
}

export async function optimizeTrafficRoute(route, google, departureTime = new Date()) {
  const stops = route.stops;
  if (!stops.length) return route;

  const requestedWaypoints = stops.slice(0, -1);
  const service = new google.maps.DirectionsService();
  const result = await service.route({
    origin: { lat: route.origin.lat, lng: route.origin.lon },
    destination: { lat: stops[stops.length - 1].lat, lng: stops[stops.length - 1].lon },
    waypoints: requestedWaypoints.map((stop) => ({
      location: { lat: stop.lat, lng: stop.lon },
      stopover: true,
    })),
    optimizeWaypoints: true,
    travelMode: google.maps.TravelMode.DRIVING,
    drivingOptions: {
      departureTime,
      trafficModel: google.maps.TrafficModel.BEST_GUESS,
    },
    provideRouteAlternatives: false,
  });

  const selectedRoute = result.routes?.[0];
  if (result.status !== "OK" || !selectedRoute?.legs?.length || !selectedRoute.overview_path?.length) {
    throw new Error(`Google traffic-aware directions failed: ${result.status || "invalid response"}.`);
  }

  const waypointOrder = selectedRoute.waypoint_order || [];
  if (waypointOrder.length !== requestedWaypoints.length) {
    throw new Error("Google traffic-aware directions returned an incomplete stop order.");
  }
  if (selectedRoute.legs.some((leg) => !Number.isFinite(leg.duration_in_traffic?.value))) {
    throw new Error("Google directions did not return traffic-adjusted travel times.");
  }

  const orderedStops = [
    ...waypointOrder.map((index) => requestedWaypoints[index]),
    stops[stops.length - 1],
  ].map((stop, index) => ({ ...stop, sequence: index + 1 }));

  return {
    ...route,
    stops: orderedStops,
    geometry: selectedRoute.overview_path.map((point) => [point.lng(), point.lat()]),
    distance_meters: Math.round(selectedRoute.legs.reduce(
      (total, leg) => total + (leg.distance?.value || 0),
      0,
    )),
    duration_seconds: Math.round(selectedRoute.legs.reduce(
      (total, leg) => total + leg.duration_in_traffic.value,
      0,
    )),
    provider: "Google Maps · Live traffic",
    trafficAware: true,
  };
}
