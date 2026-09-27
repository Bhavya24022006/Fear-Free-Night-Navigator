import axios from "axios";

// In development the CRA proxy (package.json) forwards these paths to :8000.
const api = axios.create({
  baseURL: process.env.REACT_APP_API_BASE_URL || "",
});

export async function fetchCities() {
  const { data } = await api.get("/cities/");
  return data;
}

export async function detectCity(lat, lon) {
  const { data } = await api.get("/cities/detect", { params: { lat, lon } });
  return data;
}

export async function fetchRoute(params, signal) {
  const { data } = await api.get("/route/", { params, signal });
  return data;
}

export async function fetchHeatmap(params, signal) {
  const { data } = await api.get("/heatmap/", { params, signal });
  return data;
}

export async function submitReport(report) {
  const { data } = await api.post("/report/", report);
  return data;
}

export function isCancelled(error) {
  return axios.isCancel(error) || error?.code === "ERR_CANCELED" || error?.name === "CanceledError";
}

export default api;
