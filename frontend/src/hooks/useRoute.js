import { useCallback, useRef, useState } from "react";

import { fetchRoute, isCancelled } from "../api";
import { DEFAULT_CITY } from "../constants";

// Fetches the safe and fast routes. Only the most recent request is allowed
// to update state; older in-flight requests are aborted.
export default function useRoute() {
  const [routes, setRoutes] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const controllerRef = useRef(null);
  const latestRequest = useRef(0);

  const fetchRoutes = useCallback(async ({
    originLat,
    originLon,
    destLat,
    destLon,
    alpha = 0.7,
    hour = new Date().getHours(),
    city = DEFAULT_CITY,
    autoDetect = false,
    mode = "car",
  }) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestId = ++latestRequest.current;
    const isLatest = () => requestId === latestRequest.current;

    setLoading(true);
    setError(null);

    try {
      const data = await fetchRoute(
        {
          origin_lat: originLat,
          origin_lon: originLon,
          dest_lat: destLat,
          dest_lon: destLon,
          alpha,
          hour,
          city: city || DEFAULT_CITY,
          auto_detect: Boolean(autoDetect),
          mode: mode || "car",
        },
        controller.signal,
      );

      if (data.error === "service_unavailable") {
        setError(data.message);
        return data;
      }
      if (isLatest()) setRoutes(data);
      return data;
    } catch (err) {
      if (isCancelled(err)) return null;

      const status = err?.response?.status;
      if (status === 409) return null; // replaced by a request for another city
      if (status === 400) {
        setError("Start and destination are the same place. Choose two different points.");
        return null;
      }

      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" && detail
        ? detail
        : "Could not reach the routing service. Check that the API is running.");
      return null;
    } finally {
      if (isLatest()) setLoading(false);
    }
  }, []);

  const clearRoutes = useCallback(() => {
    setRoutes(null);
    setError(null);
  }, []);

  return { routes, loading, error, fetchRoutes, clearRoutes };
}
