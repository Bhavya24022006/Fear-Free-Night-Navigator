import React, { useEffect, useState } from "react";

import { submitReport } from "../api";

const CATEGORIES = [
  { value: "unsafe", label: "Feels unsafe" },
  { value: "poor_lighting", label: "Poor lighting" },
  { value: "harassment", label: "Harassment" },
  { value: "crime", label: "Crime" },
  { value: "other", label: "Other" },
];
const MIN_LENGTH = 5;

// Button plus dialog for reporting an unsafe spot at the given position.
export default function ReportButton({ lat, lon }) {
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState("unsafe");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState("idle"); // idle | sending | sent | failed

  useEffect(() => {
    if (status !== "sent") return undefined;
    const timer = setTimeout(() => {
      setOpen(false);
      setStatus("idle");
      setDescription("");
    }, 1800);
    return () => clearTimeout(timer);
  }, [status]);

  const canSend = description.trim().length >= MIN_LENGTH && status !== "sending";

  const send = async () => {
    if (!canSend) return;
    setStatus("sending");
    try {
      await submitReport({ lat, lon, description, category, hour: new Date().getHours() });
      setStatus("sent");
    } catch (err) {
      console.error("Report failed:", err);
      setStatus("failed");
    }
  };

  return (
    <>
      <button type="button" className="btn btn--danger btn--block" onClick={() => setOpen(true)}>
        Report unsafe area
      </button>

      {open && (
        <div className="dialog-backdrop" role="presentation" onClick={() => setOpen(false)}>
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="report-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="report-title" className="dialog__title">Report an unsafe area</h2>
            <p className="dialog__text">
              The report is saved for your start point ({lat.toFixed(4)}, {lon.toFixed(4)}).
            </p>

            {status === "sent" ? (
              <div className="notice notice--guide">Thank you. Your report has been recorded.</div>
            ) : (
              <>
                <div className="field">
                  <label className="field__label" htmlFor="report-category">Category</label>
                  <select
                    id="report-category"
                    className="select"
                    value={category}
                    onChange={(event) => setCategory(event.target.value)}
                  >
                    {CATEGORIES.map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label className="field__label" htmlFor="report-text">What did you notice?</label>
                  <textarea
                    id="report-text"
                    className="textarea"
                    value={description}
                    maxLength={500}
                    placeholder="For example: street lights not working after 9 PM"
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </div>
                {status === "failed" && (
                  <div className="notice notice--error">The report could not be sent. Try again.</div>
                )}
                <div className="dialog__actions">
                  <button type="button" className="btn btn--secondary" onClick={() => setOpen(false)}>
                    Cancel
                  </button>
                  <button type="button" className="btn btn--primary" onClick={send} disabled={!canSend}>
                    {status === "sending" ? "Sending..." : "Submit report"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
