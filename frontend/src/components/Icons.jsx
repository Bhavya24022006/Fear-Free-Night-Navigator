import React from "react";

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

// Rotation of the base "straight ahead" arrow for each manoeuvre type.
const TURN_ROTATION = {
  straight: 0,
  slight_right: 45,
  right: 90,
  sharp_right: 135,
  uturn: 180,
  sharp_left: -135,
  left: -90,
  slight_left: -45,
};

export function TurnIcon({ type, size = 16 }) {
  if (type === "start") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="5" fill="currentColor" />
      </svg>
    );
  }
  if (type === "arrive") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" {...stroke}>
        <path d="M6 21V4" />
        <path d="M6 4h11l-2 4 2 4H6" />
      </svg>
    );
  }
  const angle = TURN_ROTATION[type] ?? 0;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" {...stroke}>
      <g transform={`rotate(${angle} 12 12)`}>
        <path d="M12 20V5" />
        <path d="M6 11l6-6 6 6" />
      </g>
    </svg>
  );
}

export function LocateIcon({ size = 15 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" {...stroke}>
      <circle cx="12" cy="12" r="7" />
      <circle cx="12" cy="12" r="2" fill="currentColor" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
    </svg>
  );
}
