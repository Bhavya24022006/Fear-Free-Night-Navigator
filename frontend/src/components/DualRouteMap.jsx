import React, { useEffect, useRef, useState } from "react";
import {
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  ZoomControl,
  useMap,
  useMapEvents,
} from "react-leaflet";
import L from "leaflet";

import { LocateIcon } from "./Icons";
import { MAP_STYLES, ROUTE_COLORS } from "../constants";

function pinIcon(className, label = "") {
  const size = className === "pin--me" ? 18 : 28;
  return L.divIcon({
    className: "",
    html: `<div class="pin ${className}">${label}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -size / 2],
  });
}

const START_ICON = pinIcon("pin--start", "A");
const END_ICON = pinIcon("pin--end", "B");
const USER_ICON = pinIcon("pin--me");

function ClickHandler({ onMapClick }) {
  useMapEvents({ click: (event) => onMapClick?.(event) });
  return null;
}

function FlyToCity({ center }) {
  const map = useMap();
  useEffect(() => {
    if (center) map.flyTo(center, 13, { duration: 1.5 });
  }, [map, center]);
  return null;
}

function FitToRoute({ routes }) {
  const map = useMap();
  useEffect(() => {
    const coords = routes?.safe_route?.coords || [];
    if (coords.length < 2) return;
    map.flyToBounds(L.latLngBounds(coords), { padding: [48, 48], duration: 1 });
  }, [map, routes]);
  return null;
}

// One colour per quarter of the city's roads, safest to riskiest (as in the legend).
const RISK_COLORS = ["#fde68a", "#f59e0b", "#e4572e", "#b91c1c"];

// One dot per sampled road segment, coloured by its risk relative to the city
// (0 safest, 1 riskiest). Dots, unlike a heat layer, do not add up where roads
// are dense, so the colour shows risk rather than road density.
function RiskDotsLayer({ points }) {
  const map = useMap();
  useEffect(() => {
    if (!points.length) return undefined;
    const renderer = L.canvas({ padding: 0.5 });
    const layer = L.layerGroup(
      points.map(([lat, lon, risk]) => L.circleMarker([lat, lon], {
        renderer,
        radius: 4,
        stroke: false,
        fillColor: RISK_COLORS[Math.min(RISK_COLORS.length - 1, Math.floor(risk * RISK_COLORS.length))],
        fillOpacity: 0.8,
        interactive: false,
      })),
    ).addTo(map);
    return () => map.removeLayer(layer);
  }, [map, points]);
  return null;
}

function MapToolbar({ mapStyleId, onMapStyleChange, showHeatmap, onToggleHeatmap, onLocate }) {
  const map = useMap();
  const ref = useRef(null);
  const [locating, setLocating] = useState(false);

  // Keep clicks on the toolbar from also setting a trip point on the map.
  useEffect(() => {
    if (ref.current) {
      L.DomEvent.disableClickPropagation(ref.current);
      L.DomEvent.disableScrollPropagation(ref.current);
    }
  }, []);

  const locate = () => {
    setLocating(true);
    map.locate({ setView: true, maxZoom: 15 });
    map.once("locationfound", (event) => {
      setLocating(false);
      onLocate({ lat: event.latlng.lat, lon: event.latlng.lng });
    });
    map.once("locationerror", () => {
      setLocating(false);
      window.alert("Location access was denied or is unavailable.");
    });
  };

  return (
    <div className="map-toolbar" ref={ref}>
      <select
        className="select select--compact"
        aria-label="Base map"
        value={mapStyleId}
        onChange={(event) => onMapStyleChange(event.target.value)}
      >
        {MAP_STYLES.map((style) => (
          <option key={style.id} value={style.id}>{style.label} map</option>
        ))}
      </select>
      <button
        type="button"
        className={`icon-btn ${showHeatmap ? "icon-btn--active" : ""}`}
        aria-pressed={showHeatmap}
        onClick={onToggleHeatmap}
      >
        Risk map
      </button>
      <button type="button" className="icon-btn" onClick={locate} disabled={locating}>
        <LocateIcon />
        {locating ? "Locating..." : "My location"}
      </button>
    </div>
  );
}

function RoutePopup({ title, route }) {
  return (
    <Popup>
      <strong>{title}</strong>
      <br />
      Safety {route.avg_safety_score.toFixed(1)} / 100 (grade {route.safety_grade})
      <br />
      {route.total_time_min.toFixed(1)} min · {route.total_dist_km.toFixed(1)} km
    </Popup>
  );
}

function Legend({ showHeatmap }) {
  return (
    <div className="map-legend" aria-label="Map legend">
      <div className="map-legend__row">
        <span className="route-row__swatch" /> Safer route
      </div>
      <div className="map-legend__row">
        <span className="route-row__swatch route-row__swatch--fast" /> Faster route
      </div>
      {showHeatmap && (
        <div style={{ marginTop: 8 }}>
          Road risk, relative to this city
          <div className="map-legend__gradient" />
          <div className="map-legend__ends">
            <span>Safest 25%</span>
            <span>Riskiest 25%</span>
          </div>
        </div>
      )}
    </div>
  );
}

export default function DualRouteMap({
  routes,
  origin,
  destination,
  userLocation,
  heatmapData,
  showHeatmap,
  onToggleHeatmap,
  onMapClick,
  onLocate,
  mapStyle,
  onMapStyleChange,
  cityCenter,
  status,
}) {
  const safe = routes?.safe_route;
  const fast = routes?.fast_route;

  return (
    <>
      <MapContainer center={cityCenter} zoom={13} zoomControl={false} style={{ height: "100%", width: "100%" }}>
        <TileLayer key={mapStyle.id} url={mapStyle.url} attribution={mapStyle.attribution} />
        <ZoomControl position="bottomright" />
        <ClickHandler onMapClick={onMapClick} />
        <FlyToCity center={cityCenter} />
        {routes && <FitToRoute routes={routes} />}
        {showHeatmap && heatmapData.length > 0 && <RiskDotsLayer points={heatmapData} />}

        {safe?.coords && (
          <Polyline positions={safe.coords} pathOptions={{ color: ROUTE_COLORS.safe, weight: 6, opacity: 0.9 }}>
            <RoutePopup title="Safer route" route={safe} />
          </Polyline>
        )}
        {fast?.coords && (
          <Polyline
            positions={fast.coords}
            pathOptions={{ color: ROUTE_COLORS.fast, weight: 4, opacity: 0.85, dashArray: "8 8" }}
          >
            <RoutePopup title="Faster route" route={fast} />
          </Polyline>
        )}

        {userLocation && (
          <Marker position={[userLocation.lat, userLocation.lon]} icon={USER_ICON}>
            <Popup>Your location</Popup>
          </Marker>
        )}
        {origin && (
          <Marker position={[origin.lat, origin.lon]} icon={START_ICON}>
            <Popup>Start</Popup>
          </Marker>
        )}
        {destination && (
          <Marker position={[destination.lat, destination.lon]} icon={END_ICON}>
            <Popup>Destination</Popup>
          </Marker>
        )}

        <MapToolbar
          mapStyleId={mapStyle.id}
          onMapStyleChange={onMapStyleChange}
          showHeatmap={showHeatmap}
          onToggleHeatmap={onToggleHeatmap}
          onLocate={onLocate}
        />
      </MapContainer>

      <Legend showHeatmap={showHeatmap} />

      {status && (
        <div className="map-status" role="status">
          <span className="spinner" aria-hidden="true" />
          {status}
        </div>
      )}
    </>
  );
}
