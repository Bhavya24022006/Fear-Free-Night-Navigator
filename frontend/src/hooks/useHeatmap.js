import { useCallback, useRef, useState } from "react";

import { fetchHeatmap as requestHeatmap, isCancelled } from "../api";
import { DEFAULT_CITY, HEATMAP_POINTS } from "../constants";

// Risk of each point relative to the rest of the sample: 0 for the safest
// road, 1 for the least safe. Most scores sit in a narrow band, so a fixed
// 0-100 scale would paint nearly every road the same colour.
function relativeRisk(points) {
  const sorted = points.map(([, , score]) => score).sort((a, b) => a - b);
  const last = Math.max(sorted.length - 1, 1);
  const rankOf = (score) => {
    let low = 0;
    let high = sorted.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (sorted[mid] < score) low = mid + 1;
      else high = mid;
    }
    return low;
  };
  return points.map(([lat, lon, score]) => [lat, lon, 1 - rankOf(score) / last]);
}

// Loads sampled road-safety points for a city as [lat, lon, relative risk].
export default function useHeatmap() {
  const [heatmapData, setHeatmapData] = useState([]);
  const [loading, setLoading] = useState(false);
  const controllerRef = useRef(null);
  const latestRequest = useRef(0);

  const fetchHeatmap = useCallback(async (sampleN = HEATMAP_POINTS, city = DEFAULT_CITY) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestId = ++latestRequest.current;
    const isLatest = () => requestId === latestRequest.current;

    setLoading(true);
    try {
      const data = await requestHeatmap({ sample_n: sampleN, city }, controller.signal);
      if (isLatest()) setHeatmapData(relativeRisk(data.points));
    } catch (err) {
      if (isCancelled(err) || err?.response?.status === 409) return;
      setHeatmapData([]);
    } finally {
      if (isLatest()) setLoading(false);
    }
  }, []);

  return { heatmapData, loading, fetchHeatmap };
}
