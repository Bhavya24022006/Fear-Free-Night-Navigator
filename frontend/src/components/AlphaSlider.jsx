import React from "react";

function preferenceLabel(alpha) {
  if (alpha >= 0.8) return "Max safety";
  if (alpha >= 0.6) return "Safety first";
  if (alpha >= 0.4) return "Balanced";
  if (alpha >= 0.2) return "Speed first";
  return "Max speed";
}

// Weight given to safety versus travel time (0 = fastest, 1 = safest).
export default function AlphaSlider({ alpha, onChange, lockedReason, hint }) {
  const locked = Boolean(lockedReason);
  return (
    <div className="field">
      <label className="field__label" htmlFor="alpha-slider">
        Safety preference
        <span className="field__value">
          {preferenceLabel(alpha)} ({alpha.toFixed(1)})
        </span>
      </label>
      <input
        id="alpha-slider"
        className="range"
        type="range"
        min="0"
        max="1"
        step="0.1"
        value={alpha}
        disabled={locked}
        onChange={(event) => onChange(parseFloat(event.target.value))}
      />
      <div className="range__ends">
        <span>Fastest</span>
        <span>Safest</span>
      </div>
      {(lockedReason || hint) && <p className="field__hint">{lockedReason || hint}</p>}
    </div>
  );
}
