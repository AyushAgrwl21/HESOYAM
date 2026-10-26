import { useState } from "react";
import type { SeriesInterval, SeriesResponse } from "../api/types";
import { formatCount, formatMatchStatus, formatMeasuredMw } from "../format/display";

export function SettlementTable({ series }: { series: SeriesResponse }) {
  const [gapsOnly, setGapsOnly] = useState(false);
  const rows = gapsOnly
    ? series.intervals.filter((interval) => interval.match_status !== "matched")
    : series.intervals;
  const timezone = series.window.decision_timezone;

  return (
    <section className="table-section">
      <div className="section-heading">
        <h3>Settlement periods</h3>
        <label className="check">
          <input
            type="checkbox"
            checked={gapsOnly}
            onChange={(event) => setGapsOnly(event.target.checked)}
          />
          Show only unmatched intervals
        </label>
      </div>
      <p className="note">
        {formatCount(series.interval_count)} intervals. {series.window_note}
      </p>
      {rows.length === 0 ? (
        <p className="state">
          {gapsOnly
            ? "Every returned interval is matched."
            : "No settlement intervals were returned."}
        </p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Period</th>
                <th scope="col">Local start ({timezone})</th>
                <th scope="col">Start time (UTC)</th>
                <th scope="col">Actual</th>
                <th scope="col">Decision-time forecast</th>
                <th scope="col">Signed error</th>
                <th scope="col">Absolute error</th>
                <th scope="col">Selected publishTime</th>
                <th scope="col">Cutoff (UTC)</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((interval) => (
                <tr key={interval.start_time_utc} className={rowClass(interval)}>
                  <td>{interval.settlement_period}</td>
                  <td>{interval.local_start_time}</td>
                  <td>{interval.start_time_utc}</td>
                  <td className="numeric">{formatMeasuredMw(interval.actual_generation_mw, interval.actual_measurement)}</td>
                  <td className="numeric">{formatMeasuredMw(interval.forecast_generation_mw, interval.forecast_measurement)}</td>
                  <td className="numeric">{formatError(interval.signed_error_mw)}</td>
                  <td className="numeric">{formatError(interval.absolute_error_mw)}</td>
                  <td>{interval.selected_publish_time_utc ?? "None"}</td>
                  <td>{interval.cutoff_utc}</td>
                  <td>{formatMatchStatus(interval.match_status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function formatError(value: number | null): string {
  return value === null ? "Not calculated" : `${formatCount(value)} MW`;
}

function rowClass(interval: SeriesInterval): string {
  return interval.match_status === "matched" ? "" : "row-gap";
}
