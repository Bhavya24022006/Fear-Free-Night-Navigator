import React from "react";

import { TurnIcon } from "./Icons";
import { GRADE_COLORS } from "../constants";

function formatDistance(metres) {
  if (!metres) return "";
  return metres >= 1000 ? `${(metres / 1000).toFixed(1)} km` : `${Math.round(metres)} m`;
}

export default function DirectionsPanel({ directions, currentStep, onSelectStep, guidance }) {
  if (!directions || directions.length === 0) {
    return (
      <div className="empty">
        Plan a route to see turn-by-turn directions for the safer route.
      </div>
    );
  }

  return (
    <>
      {guidance && <div className="notice notice--guide">{guidance}</div>}
      <ol className="steps">
        {directions.map((step, index) => (
          <li key={`${step.step}-${index}`}>
            <button
              type="button"
              className={`step ${index === currentStep ? "step--current" : ""}`}
              onClick={() => onSelectStep(index)}
              aria-current={index === currentStep ? "step" : undefined}
            >
              <span className="step__icon">
                <TurnIcon type={step.type} />
              </span>
              <span className="step__body">
                <span className="step__text">{step.instruction}</span>
                <span className="step__meta">
                  {formatDistance(step.distance_m) && <span>{formatDistance(step.distance_m)}</span>}
                  <span
                    className="grade"
                    style={{ background: GRADE_COLORS[step.safety_grade] || "#6b7480" }}
                    title={`Safety ${Number(step.safety_score).toFixed(0)} / 100`}
                  >
                    {step.safety_grade}
                  </span>
                  <span>Safety {Number(step.safety_score).toFixed(0)}</span>
                </span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </>
  );
}
