import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import DirectionsPanel from "./components/DirectionsPanel";
import DualRouteMap from "./components/DualRouteMap";
import ReportButton from "./components/ReportButton";
import SafetyBar from "./components/SafetyBar";
import TravelOptions from "./components/TravelOptions";
import TripPlanner from "./components/TripPlanner";
import useHeatmap from "./hooks/useHeatmap";
import useRoute from "./hooks/useRoute";
import { detectCity, fetchCities } from "./api";
import {
  CITY_CENTERS,
  DEFAULT_CITY,
  HEATMAP_POINTS,
  INDIA_CENTER,
  MAP_STYLES,
  WOMEN_MODE_ALPHA,
  landmarksFor,
} from "./constants";

const HIGH_RISK_BELOW = 40;

// Short guidance line for the step the traveller is on.
function guidanceFor(step) {
  if (!step) return "";
  const score = step.safety_score ?? 50;
  if (score < 30) {
    return `Caution: higher-risk stretch. ${step.instruction}. Keep to well-lit, busy roads.`;
  }
  if (score > 70) {
    return `Safer stretch ahead. ${step.instruction}.`;
  }
  return step.instruction;
}

function whatsappShareUrl(location) {
  const mapLink = `https://maps.google.com/?q=${location.lat},${location.lon}`;
  const text = [
    "I'm sharing my live location for safety.",
    `Current location: ${mapLink}`,
    "Sent from Fear-Free Navigator.",
  ].join("\n");
  return `https://wa.me/?text=${encodeURIComponent(text)}`;
}

export default function App() {
  const [cities, setCities] = useState([DEFAULT_CITY]);
  const [selectedCity, setSelectedCity] = useState(DEFAULT_CITY);
  const cityRef = useRef(DEFAULT_CITY);
  const [cityCenter, setCityCenter] = useState(CITY_CENTERS[DEFAULT_CITY]);

  const [origin, setOrigin] = useState(null);
  const [destination, setDestination] = useState(null);
  const [nextPoint, setNextPoint] = useState("origin");
  const [userLocation, setUserLocation] = useState(null);

  const [travelMode, setTravelMode] = useState("car");
  const [hour, setHour] = useState(new Date().getHours());
  const [alpha, setAlpha] = useState(0.7);
  const [womenMode, setWomenMode] = useState(false);

  const [showHeatmap, setShowHeatmap] = useState(true);
  const [mapStyle, setMapStyle] = useState(MAP_STYLES[0]);
  const [serviceError, setServiceError] = useState(null);
  const [tab, setTab] = useState("plan");
  const [tripStarted, setTripStarted] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);

  const { routes, loading, error, fetchRoutes, clearRoutes } = useRoute();
  const { heatmapData, loading: cityLoading, fetchHeatmap } = useHeatmap();

  const effectiveAlpha = womenMode ? WOMEN_MODE_ALPHA : alpha;
  const directions = routes?.safe_route?.directions || [];
  const places = useMemo(() => landmarksFor(selectedCity), [selectedCity]);

  useEffect(() => {
    cityRef.current = selectedCity;
  }, [selectedCity]);

  // The heatmap request also makes the server load the city's road network.
  useEffect(() => {
    fetchHeatmap(HEATMAP_POINTS, selectedCity);
  }, [selectedCity, fetchHeatmap]);

  // Re-plan whenever the trip or a preference changes.
  useEffect(() => {
    if (!origin || !destination) return;
    setServiceError(null);
    fetchRoutes({
      originLat: origin.lat,
      originLon: origin.lon,
      destLat: destination.lat,
      destLon: destination.lon,
      alpha: effectiveAlpha,
      hour,
      city: cityRef.current,
      mode: travelMode,
      autoDetect: false,
    }).then((result) => {
      if (result?.error === "service_unavailable") setServiceError(result);
    });
  }, [origin, destination, effectiveAlpha, hour, selectedCity, travelMode, fetchRoutes]);

  const resetTrip = useCallback(() => {
    setOrigin(null);
    setDestination(null);
    setUserLocation(null);
    setServiceError(null);
    setTripStarted(false);
    setCurrentStep(0);
    setNextPoint("origin");
    setTab("plan");
    clearRoutes();
  }, [clearRoutes]);

  const changeCity = useCallback((city) => {
    setSelectedCity(city);
    cityRef.current = city;
    resetTrip();
    setCityCenter(CITY_CENTERS[city] || INDIA_CENTER);
  }, [resetTrip]);

  // Load the list of cities with data; fall back to the first one if the
  // default city is not among them.
  useEffect(() => {
    fetchCities()
      .then((data) => {
        if (!data.cities?.length) return;
        setCities(data.cities);
        if (!data.cities.includes(cityRef.current)) changeCity(data.cities[0]);
      })
      .catch(() => {});
  }, [changeCity]);

  const setPoint = useCallback((which, point) => {
    if (which === "origin") {
      setOrigin(point);
      setNextPoint("destination");
    } else {
      setDestination(point);
      setNextPoint("origin");
    }
  }, []);

  const handleMapClick = useCallback((event) => {
    setPoint(nextPoint, { lat: event.latlng.lat, lon: event.latlng.lng });
  }, [nextPoint, setPoint]);

  const handleLocate = useCallback((location) => {
    setUserLocation(location);
    setPoint("origin", location);
    detectCity(location.lat, location.lon)
      .then((data) => {
        if (data.city) {
          setSelectedCity(data.city);
          cityRef.current = data.city;
        }
      })
      .catch(() => {});
  }, [setPoint]);

  const startTrip = () => {
    if (!routes) return;
    setTripStarted(true);
    setCurrentStep(0);
    setTab("directions");
  };

  const isHighRisk = routes?.safe_route?.avg_safety_score < HIGH_RISK_BELOW;
  const offerSharing = isHighRisk || womenMode;
  const guidance = tripStarted ? guidanceFor(directions[currentStep] || directions[0]) : "";

  let mapStatus = null;
  if (cityLoading) mapStatus = `Loading ${selectedCity} road network...`;
  else if (loading) mapStatus = "Calculating routes...";

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="sidebar__header">
          <h1 className="brand__title">Fear-Free Navigator</h1>
          <p className="brand__subtitle">Safer routes across Indian cities · {selectedCity}</p>
        </header>

        <nav className="tabs" aria-label="Sidebar sections">
          <button
            type="button"
            className={`tab ${tab === "plan" ? "tab--active" : ""}`}
            onClick={() => setTab("plan")}
          >
            Plan trip
          </button>
          <button
            type="button"
            className={`tab ${tab === "directions" ? "tab--active" : ""}`}
            onClick={() => setTab("directions")}
          >
            Directions
            {directions.length > 0 && <span className="tab__count">{directions.length}</span>}
          </button>
        </nav>

        <div className="sidebar__body">
          {tab === "plan" ? (
            <>
              {serviceError && (
                <div className="notice notice--warning">
                  <span className="notice__title">City not available yet</span>
                  {serviceError.message}{" "}
                  {serviceError.suggestion && (
                    <button
                      type="button"
                      className="btn btn--link"
                      onClick={() => changeCity(serviceError.suggestion.split(": ")[1])}
                    >
                      Switch to {serviceError.suggestion.split(": ")[1]}
                    </button>
                  )}
                </div>
              )}
              {error && !serviceError && <div className="notice notice--error">{error}</div>}

              <TripPlanner
                cities={cities}
                city={selectedCity}
                onCityChange={changeCity}
                origin={origin}
                destination={destination}
                nextPoint={nextPoint}
                onNextPointChange={setNextPoint}
                places={places}
                onPickOrigin={(place) => setPoint("origin", { lat: place.lat, lon: place.lon })}
                onPickDestination={(place) => setPoint("destination", { lat: place.lat, lon: place.lon })}
              />

              <TravelOptions
                mode={travelMode}
                onModeChange={setTravelMode}
                hour={hour}
                onHourChange={setHour}
                alpha={alpha}
                onAlphaChange={setAlpha}
                womenMode={womenMode}
                onToggleWomenMode={() => setWomenMode((on) => !on)}
              />

              <section className="section">
                <h2 className="section__title">Routes</h2>
                {loading && <p className="muted">Calculating the safer and the faster route...</p>}
                {!loading && routes && !serviceError && (
                  <SafetyBar
                    safeRoute={routes.safe_route}
                    fastRoute={routes.fast_route}
                    comparison={routes.comparison}
                  />
                )}
                {!loading && !routes && (
                  <p className="muted">Choose a start and a destination to compare routes.</p>
                )}
              </section>

              <div className="actions">
                <button
                  type="button"
                  className="btn btn--primary btn--block"
                  onClick={startTrip}
                  disabled={!routes || loading}
                >
                  Start trip on the safer route
                </button>

                {offerSharing && routes && (
                  userLocation ? (
                    <a
                      className="btn btn--secondary btn--block"
                      href={whatsappShareUrl(userLocation)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Share live location on WhatsApp
                    </a>
                  ) : (
                    <p className="muted">Use "My location" on the map to enable location sharing.</p>
                  )
                )}

                <div className="actions__row">
                  {origin ? (
                    <ReportButton lat={origin.lat} lon={origin.lon} />
                  ) : (
                    <button type="button" className="btn btn--danger btn--block" disabled>
                      Report unsafe area
                    </button>
                  )}
                  <button type="button" className="btn btn--secondary btn--block" onClick={resetTrip}>
                    Clear trip
                  </button>
                </div>
              </div>
            </>
          ) : (
            <DirectionsPanel
              directions={directions}
              currentStep={currentStep}
              onSelectStep={setCurrentStep}
              guidance={guidance}
            />
          )}
        </div>

        <footer className="sidebar__footer">
          Safety scores are estimates from open data, not guarantees.
        </footer>
      </aside>

      <main className="map-area">
        <DualRouteMap
          routes={routes}
          origin={origin}
          destination={destination}
          userLocation={userLocation}
          heatmapData={heatmapData}
          showHeatmap={showHeatmap}
          onToggleHeatmap={() => setShowHeatmap((on) => !on)}
          onMapClick={handleMapClick}
          onLocate={handleLocate}
          mapStyle={mapStyle}
          onMapStyleChange={(id) => setMapStyle(MAP_STYLES.find((style) => style.id === id) || MAP_STYLES[0])}
          cityCenter={cityCenter}
          status={mapStatus}
        />
      </main>
    </div>
  );
}
