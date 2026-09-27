import React from "react";

import { GRADE_COLORS } from "../constants";

function GradeBadge({ grade }) {
  return (
    <span className="grade" style={{ background: GRADE_COLORS[grade] || "#6b7480" }}>
      {grade}
    </span>
  );
}

function signed(value, digits) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function RouteRow({ title, route, variant }) {
  const score = route.avg_safety_score;
  return (
    <div className="route-row">
      <div className="route-row__head">
        <span className={`route-row__swatch ${variant === "fast" ? "route-row__swatch--fast" : ""}`} />
        <span className="route-row__name">{title}</span>
        <span className="route-row__score">
          {score.toFixed(1)} <small>/ 100</small>
        </span>
        <GradeBadge grade={route.safety_grade} />
      </div>
      <div className="bar">
        <div
          className="bar__fill"
          style={{
            width: `${Math.max(0, Math.min(100, score))}%`,
            background: GRADE_COLORS[route.safety_grade] || "#6b7480",
          }}
        />
      </div>
      <div className="route-row__meta">
        {route.total_time_min.toFixed(1)} min · {route.total_dist_km.toFixed(1)} km ·{" "}
        {(route.risky_km ?? 0).toFixed(1)} km on high-risk roads ({Math.round(route.risky_share_pct ?? 0)}%)
      </div>
    </div>
  );
}

// Side-by-side summary of the safer and the faster route.
export default function SafetyBar({ safeRoute, fastRoute, comparison }) {
  if (!safeRoute || !fastRoute) return null;

  const gain = comparison?.safety_gain_points ?? 0;
  const extra = comparison?.time_penalty_min ?? 0;
  const avoided = comparison?.risky_km_avoided ?? 0;
  const worthIt = Boolean(comparison?.safer_route_worth_it);

  return (
    <div className="compare">
      <RouteRow title="Safer route" route={safeRoute} variant="safe" />
      <RouteRow title="Faster route" route={fastRoute} variant="fast" />
      <div className={`verdict ${worthIt ? "verdict--good" : "verdict--caution"}`}>
        <strong>{signed(gain, 1)} safety points per km</strong> and{" "}
        <strong>{avoided.toFixed(1)} km {avoided >= 0 ? "less" : "more"}</strong> on high-risk roads
        for <strong>{signed(extra, 1)} min</strong>. {comparison?.recommendation}
        {comparison?.high_risk_below != null && (
          <span className="verdict__note">
            High-risk: roads scoring under {comparison.high_risk_below} at this hour (grades D and E).
            Safety points are averaged per km.
          </span>
        )}
      </div>
    </div>
  );
}
