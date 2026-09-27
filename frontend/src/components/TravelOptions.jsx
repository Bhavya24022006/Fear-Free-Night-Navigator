import React from "react";

import AlphaSlider from "./AlphaSlider";
import {
  MODE_FIXED_ALPHA,
  MODE_MIN_ALPHA,
  MODE_NOTES,
  TRAVEL_MODES,
  WOMEN_MODE_ALPHA,
  formatHour,
  periodForHour,
} from "../constants";

// The safety weight the server will use, and why the slider is locked or
// partly ignored, for the chosen mode.
function sliderState(mode, alpha, womenMode) {
  const modeLabel = TRAVEL_MODES.find((option) => option.id === mode)?.label || mode;
  if (womenMode) {
    return { value: WOMEN_MODE_ALPHA, lockedReason: "Set to 0.9 while Women Safety Mode is on." };
  }
  if (MODE_FIXED_ALPHA[mode] != null) {
    return {
      value: MODE_FIXED_ALPHA[mode],
      lockedReason: `${modeLabel} always uses ${MODE_FIXED_ALPHA[mode]}.`,
    };
  }
  const floor = MODE_MIN_ALPHA[mode];
  if (floor != null && alpha < floor) {
    return { value: alpha, hint: `${modeLabel} uses at least ${floor}, so lower values give the same route.` };
  }
  return { value: alpha };
}

export default function TravelOptions({
  mode,
  onModeChange,
  hour,
  onHourChange,
  alpha,
  onAlphaChange,
  womenMode,
  onToggleWomenMode,
}) {
  const slider = sliderState(mode, alpha, womenMode);
  return (
    <section className="section">
      <h2 className="section__title">Preferences</h2>

      <div className="field">
        <span className="field__label">Travel mode</span>
        <div className="segmented" role="group" aria-label="Travel mode">
          {TRAVEL_MODES.map((option) => (
            <button
              key={option.id}
              type="button"
              className={`segmented__option ${mode === option.id ? "segmented__option--active" : ""}`}
              aria-pressed={mode === option.id}
              onClick={() => onModeChange(option.id)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <p className="field__hint">{MODE_NOTES[mode]}</p>
      </div>

      <div className="field">
        <label className="field__label" htmlFor="hour-slider">
          Time of travel
          <span className="field__value">
            {formatHour(hour)} · {periodForHour(hour)}
          </span>
        </label>
        <input
          id="hour-slider"
          className="range"
          type="range"
          min="0"
          max="23"
          step="1"
          value={hour}
          onChange={(event) => onHourChange(parseInt(event.target.value, 10))}
        />
        <div className="range__ends">
          <span>00:00</span>
          <span>23:00</span>
        </div>
      </div>

      <AlphaSlider
        alpha={slider.value}
        onChange={onAlphaChange}
        lockedReason={slider.lockedReason}
        hint={slider.hint}
      />

      <button
        type="button"
        className={`toggle ${womenMode ? "toggle--on" : ""}`}
        onClick={onToggleWomenMode}
        role="switch"
        aria-checked={womenMode}
      >
        <span className="toggle__track">
          <span className="toggle__thumb" />
        </span>
        <span>
          <span className="toggle__title">Women Safety Mode</span>
          <span className="toggle__desc">
            Uses the highest safety weighting and enables live location sharing.
          </span>
        </span>
      </button>
    </section>
  );
}
