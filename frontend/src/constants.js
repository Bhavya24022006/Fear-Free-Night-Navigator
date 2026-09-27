// Static configuration shared by the UI components.

export const DEFAULT_CITY = "Bengaluru";
export const INDIA_CENTER = [20.5937, 78.9629];
export const HEATMAP_POINTS = 3000;

export const CITY_CENTERS = {
  Agra: [27.1767, 78.0081],
  Ahmedabad: [23.0225, 72.5714],
  Aligarh: [27.8974, 78.088],
  Allahabad: [25.4358, 81.8463],
  Amritsar: [31.634, 74.8723],
  Aurangabad: [19.8762, 75.3433],
  Bengaluru: [12.9716, 77.5946],
  Bhavnagar: [21.7645, 72.1519],
  Bhopal: [23.2599, 77.4126],
  Bhubaneswar: [20.2961, 85.8245],
  Bikaner: [28.0229, 73.3119],
  Chandigarh: [30.7333, 76.7794],
  Chennai: [13.0827, 80.2707],
  Coimbatore: [11.0168, 76.9558],
  Dehradun: [30.3165, 78.0322],
  Delhi: [28.6139, 77.209],
  Faridabad: [28.4089, 77.3178],
  Ghaziabad: [28.6692, 77.4538],
  Goa: [15.4909, 73.8278],
  Guntur: [16.3067, 80.4365],
  Gurugram: [28.4595, 77.0266],
  Guwahati: [26.1445, 91.7362],
  Gwalior: [26.2183, 78.1828],
  Hubli: [15.3647, 75.124],
  Hyderabad: [17.385, 78.4867],
  Indore: [22.7196, 75.8577],
  Jabalpur: [23.1815, 79.9864],
  Jaipur: [26.9124, 75.7873],
  Jamnagar: [22.4707, 70.0577],
  Jodhpur: [26.2389, 73.0243],
  Kanpur: [26.4499, 80.3319],
  Kochi: [9.9312, 76.2673],
  Kolhapur: [16.705, 74.2433],
  Kolkata: [22.5726, 88.3639],
  Kota: [25.2138, 75.8648],
  Kozhikode: [11.2588, 75.7804],
  Kurnool: [15.8281, 78.0373],
  Lucknow: [26.8467, 80.9462],
  Ludhiana: [30.901, 75.8573],
  Madurai: [9.9252, 78.1198],
  Mangalore: [12.9141, 74.856],
  Meerut: [28.9845, 77.7064],
  Mumbai: [19.076, 72.8777],
  Mysuru: [12.2958, 76.6394],
  Nagpur: [21.1458, 79.0882],
  Nashik: [19.9975, 73.7898],
  Nellore: [14.4426, 79.9865],
  Noida: [28.5355, 77.391],
  Patna: [25.5941, 85.1376],
  Pune: [18.5204, 73.8567],
  Raipur: [21.2514, 81.6296],
  Rajkot: [22.3039, 70.8022],
  Ranchi: [23.3441, 85.3096],
  Salem: [11.6643, 78.146],
  Siliguri: [26.7271, 88.3953],
  Solapur: [17.6599, 75.9064],
  Surat: [21.1702, 72.8311],
  Thiruvananthapuram: [8.5241, 76.9366],
  Thrissur: [10.5276, 76.2144],
  Tiruchirappalli: [10.7905, 78.7047],
  Tirunelveli: [8.7139, 77.7567],
  Tirupati: [13.6288, 79.4192],
  Vadodara: [22.3072, 73.1812],
  Varanasi: [25.3176, 82.9739],
  Vijayawada: [16.5062, 80.648],
  Visakhapatnam: [17.6868, 83.2185],
  Warangal: [17.9784, 79.5941],
};

// Well-known places offered as one-click start / destination points.
export const LANDMARKS = {
  Bengaluru: [
    { name: "MG Road", lat: 12.9767, lon: 77.6009 },
    { name: "Koramangala", lat: 12.9352, lon: 77.6245 },
    { name: "Indiranagar", lat: 12.9718, lon: 77.6412 },
    { name: "Majestic", lat: 12.9767, lon: 77.5713 },
    { name: "Whitefield", lat: 12.9698, lon: 77.7499 },
  ],
  Mumbai: [
    { name: "CST", lat: 18.9398, lon: 72.8355 },
    { name: "Bandra", lat: 19.0596, lon: 72.8295 },
    { name: "Andheri", lat: 19.1197, lon: 72.8468 },
    { name: "Dharavi", lat: 19.038, lon: 72.8528 },
    { name: "Powai", lat: 19.1197, lon: 72.9056 },
  ],
  Delhi: [
    { name: "Connaught Place", lat: 28.6315, lon: 77.2167 },
    { name: "Lajpat Nagar", lat: 28.57, lon: 77.2433 },
    { name: "Karol Bagh", lat: 28.6519, lon: 77.19 },
    { name: "Dwarka", lat: 28.5921, lon: 77.046 },
    { name: "Saket", lat: 28.5244, lon: 77.2066 },
  ],
  Chennai: [
    { name: "T Nagar", lat: 13.0418, lon: 80.2341 },
    { name: "Anna Nagar", lat: 13.085, lon: 80.2101 },
    { name: "Adyar", lat: 13.0012, lon: 80.2565 },
    { name: "Velachery", lat: 12.9789, lon: 80.2208 },
    { name: "Central", lat: 13.0827, lon: 80.2707 },
  ],
  Hyderabad: [
    { name: "Charminar", lat: 17.3616, lon: 78.4747 },
    { name: "Hitech City", lat: 17.4504, lon: 78.3805 },
    { name: "Banjara Hills", lat: 17.4126, lon: 78.4483 },
    { name: "Secunderabad", lat: 17.4399, lon: 78.4983 },
    { name: "Gachibowli", lat: 17.4401, lon: 78.3489 },
  ],
};

export function landmarksFor(city) {
  if (LANDMARKS[city]) return LANDMARKS[city];
  const center = CITY_CENTERS[city];
  return center ? [{ name: "City centre", lat: center[0], lon: center[1] }] : [];
}

// Tile sources that work without an API key (CARTO basemaps now require one).
export const MAP_STYLES = [
  {
    id: "standard",
    label: "Standard",
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: "&copy; OpenStreetMap contributors",
  },
  {
    id: "light",
    label: "Light",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    attribution: "Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
  },
  {
    id: "dark",
    label: "Dark",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    attribution: "Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
  },
  {
    id: "satellite",
    label: "Satellite",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Imagery &copy; Esri",
  },
  {
    id: "terrain",
    label: "Terrain",
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attribution: "&copy; OpenStreetMap contributors, SRTM &copy; OpenTopoMap",
  },
];

export const TRAVEL_MODES = [
  { id: "car", label: "Car" },
  { id: "motorcycle", label: "Motorbike" },
  { id: "walking", label: "Walk" },
  { id: "cycling", label: "Cycle" },
];

// Mode-specific safety weight applied by the server when alpha is left at 0.7.
export const MODE_NOTES = {
  car: "Prefers main roads.",
  motorcycle: "Uses a safety weight of at least 0.75.",
  walking: "Avoids highways; safety weight fixed at 0.9.",
  cycling: "Avoids highways; safety weight fixed at 0.85.",
};

// Safety weights the server applies whatever the slider says
// (MODE_PROFILES in routing/city_router.py).
export const MODE_FIXED_ALPHA = { walking: 0.9, cycling: 0.85 };
export const MODE_MIN_ALPHA = { motorcycle: 0.75 };

export const WOMEN_MODE_ALPHA = 0.9;

// Grade colours used for badges and step markers.
export const GRADE_COLORS = {
  A: "#2e7d32",
  B: "#689f38",
  C: "#c98a00",
  D: "#e0650b",
  E: "#c62828",
};

export const ROUTE_COLORS = {
  safe: "#2e7d32",
  fast: "#3a66a8",
};

// Time bands used by the routing engine.
export function periodForHour(hour) {
  if (hour >= 6 && hour < 17) return "Day";
  if (hour >= 17 && hour < 20) return "Evening";
  if (hour >= 20) return "Night";
  return "Late night";
}

export function gradeForScore(score) {
  if (score >= 80) return "A";
  if (score >= 60) return "B";
  if (score >= 40) return "C";
  if (score >= 20) return "D";
  return "E";
}

export function formatHour(hour) {
  return `${String(hour).padStart(2, "0")}:00`;
}

export function formatCoords(point) {
  return `${point.lat.toFixed(4)}, ${point.lon.toFixed(4)}`;
}
