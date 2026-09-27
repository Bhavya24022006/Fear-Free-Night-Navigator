import React from "react";

import { formatCoords } from "../constants";

function Stop({ kind, label, point, isNext, onSelect }) {
  return (
    <button
      type="button"
      className={`stop ${isNext ? "stop--next" : ""}`}
      onClick={onSelect}
      aria-pressed={isNext}
    >
      <span className={`stop__marker stop__marker--${kind}`}>{kind === "start" ? "A" : "B"}</span>
      <span className="stop__text">
        <span className="stop__label">
          {label}
          {isNext ? " (next map click)" : ""}
        </span>
        {point ? (
          <span className="stop__value">{formatCoords(point)}</span>
        ) : (
          <span className="stop__value stop__value--empty">Click the map or pick a place below</span>
        )}
      </span>
    </button>
  );
}

function PlaceChips({ title, places, selected, onPick }) {
  if (places.length === 0) return null;
  return (
    <>
      <p className="chips__label">{title}</p>
      <div className="chips">
        {places.map((place) => {
          const isSelected = selected?.lat === place.lat && selected?.lon === place.lon;
          return (
            <button
              key={place.name}
              type="button"
              className={`chip ${isSelected ? "chip--selected" : ""}`}
              onClick={() => onPick(place)}
            >
              {place.name}
            </button>
          );
        })}
      </div>
    </>
  );
}

export default function TripPlanner({
  cities,
  city,
  onCityChange,
  origin,
  destination,
  nextPoint,
  onNextPointChange,
  places,
  onPickOrigin,
  onPickDestination,
}) {
  return (
    <section className="section">
      <h2 className="section__title">Trip</h2>

      <div className="field">
        <label className="field__label" htmlFor="city-select">City</label>
        <select
          id="city-select"
          className="select"
          value={city}
          onChange={(event) => onCityChange(event.target.value)}
        >
          {cities.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
      </div>

      <div className="stops">
        <Stop
          kind="start"
          label="Start"
          point={origin}
          isNext={nextPoint === "origin"}
          onSelect={() => onNextPointChange("origin")}
        />
        <Stop
          kind="end"
          label="Destination"
          point={destination}
          isNext={nextPoint === "destination"}
          onSelect={() => onNextPointChange("destination")}
        />
      </div>

      <PlaceChips title="Start from" places={places} selected={origin} onPick={onPickOrigin} />
      <PlaceChips title="Go to" places={places} selected={destination} onPick={onPickDestination} />
    </section>
  );
}
