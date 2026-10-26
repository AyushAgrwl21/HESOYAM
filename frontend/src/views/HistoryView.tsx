import { useEffect } from "react";
import { parseSeries, parseVintages } from "../api/guards";
import { seriesPath, vintagesPath } from "../api/studyClient";
import type { SeriesInterval, VintagePoint, VintageResponse } from "../api/types";
import { PanelState } from "../components/PanelState";
import { ProvenanceNote } from "../components/ProvenanceNote";
import { VintageChart } from "../components/VintageChart";
import { formatCount, formatMatchStatus, formatMeasuredMw, formatUtc, plainLabel } from "../format/display";
import { useGet } from "../hooks/useGet";

export function HistoryView({
  deliveryDate,
  cutoffLocal,
  settlementPeriod,
  onSettlementPeriod,
}: {
  deliveryDate: string;
  cutoffLocal: string;
  settlementPeriod: number | null;
  onSettlementPeriod: (period: number) => void;
}) {
  const series = useGet(seriesPath({ deliveryDate, decisionCutoffLocal: cutoffLocal }), parseSeries);
  const vintages = useGet(
    settlementPeriod === null ? null : vintagesPath(deliveryDate, settlementPeriod, cutoffLocal),
    parseVintages,
  );

  useEffect(() => {
    if (!series.data) {
      return;
    }
    const periods = series.data.intervals.map((interval) => interval.settlement_period);
    if (settlementPeriod !== null && periods.includes(settlementPeriod)) {
      return;
    }
    const preferred = series.data.intervals.find((interval) => interval.forecast_measurement === "measured");
    const nextPeriod = preferred?.settlement_period ?? periods[0];
    if (nextPeriod !== undefined) {
      onSettlementPeriod(nextPeriod);
    }
  }, [series.data, settlementPeriod, onSettlementPeriod]);

  const selectedInterval = series.data?.intervals.find(
    (interval) => interval.settlement_period === settlementPeriod,
  );

  return (
    <div className="view">
      <section>
        <h2>Forecast history</h2>
        <p className="note">
          Publications after the cutoff stay on this page so they can be checked. They are not the
          forecast that was available at the decision.
        </p>
        <PanelState
          status={series.status}
          errorMessage={series.errorMessage}
          onRetry={series.retry}
          loadingLabel={`Loading settlement periods for ${deliveryDate}.`}
        >
          {series.data && series.data.interval_count === 0 ? (
            <p className="state">{series.data.window_note}</p>
          ) : series.data ? (
            <label className="field">
              Target settlement period
              <select
                value={settlementPeriod ?? ""}
                onChange={(event) => onSettlementPeriod(Number(event.target.value))}
              >
                {series.data.intervals.map((interval) => (
                  <option key={interval.start_time_utc} value={interval.settlement_period}>
                    Period {interval.settlement_period} · {interval.local_start_time} {series.data?.window.decision_timezone}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </PanelState>
      </section>

      <PanelState
        status={settlementPeriod === null ? "idle" : vintages.status}
        errorMessage={vintages.errorMessage}
        onRetry={vintages.retry}
        loadingLabel="Loading forecast vintages."
      >
        {vintages.data ? (
          <VintageDetail vintage={vintages.data} interval={selectedInterval ?? null} />
        ) : null}
      </PanelState>
    </div>
  );
}

function VintageDetail({
  vintage,
  interval,
}: {
  vintage: VintageResponse;
  interval: SeriesInterval | null;
}) {
  const evolution = vintage.evolution;
  const eligible = evolution.points.filter((point) => point.eligible_at_decision).length;
  const later = evolution.points.length - eligible;
  const selected = evolution.points.find((point) => point.selected_for_decision);
  const disagreement = interval && selected
    ? interval.selected_publish_time_utc !== selected.publish_time_utc ||
      interval.forecast_generation_mw !== selected.generation_mw
    : false;

  return (
    <section>
      {evolution.outside_scored_grid ? (
        <p className="state state-error" role="alert">
          This target is outside the scored grid. {evolution.note}
        </p>
      ) : null}
      <p className="note">
        Target {formatUtc(evolution.target_start_time_utc)}. Cutoff {formatUtc(evolution.cutoff_utc)}. Basis:{" "}
        {plainLabel(vintage.window.cutoff_basis)}.
        Decision cutoff clock: {vintage.window.decision_cutoff_local} {vintage.window.decision_timezone}.
      </p>
      <p>
        {formatCount(eligible)} publications were available at the cutoff. {formatCount(later)} were
        published after it.
      </p>
      {interval ? (
        <dl className="inline-facts">
          <div>
            <dt>Decision-time forecast</dt>
            <dd>{formatMeasuredMw(interval.forecast_generation_mw, interval.forecast_measurement)}</dd>
          </div>
          <div>
            <dt>Actual generation</dt>
            <dd>{formatMeasuredMw(interval.actual_generation_mw, interval.actual_measurement)}</dd>
          </div>
          <div>
            <dt>Selected publishTime</dt>
            <dd>{interval.selected_publish_time_utc ?? "None"}</dd>
          </div>
          <div>
            <dt>Series status</dt>
            <dd>{formatMatchStatus(interval.match_status)}</dd>
          </div>
        </dl>
      ) : null}
      {disagreement ? (
        <p className="state state-error" role="alert">
          The series and the vintage list disagree on the selected publication. Both are shown as
          returned and were not reconciled.
        </p>
      ) : null}
      {evolution.points.length === 0 ? <p className="state">{evolution.note}</p> : <VintageChart evolution={evolution} />}
      <VintageTable points={evolution.points} />
      <p className="note">{vintage.window.null_generation_meaning}</p>
      <ProvenanceNote provenance={vintage.provenance} />
    </section>
  );
}

function VintageTable({ points }: { points: VintagePoint[] }) {
  if (points.length === 0) {
    return null;
  }
  return (
    <div className="table-wrap">
      <table>
        <caption>Every cached publication of this settlement period, including those after the cutoff.</caption>
        <thead>
          <tr>
            <th scope="col">publishTime (UTC)</th>
            <th scope="col">Generation</th>
            <th scope="col">At the cutoff</th>
            <th scope="col">Decision forecast</th>
            <th scope="col">Newest cached</th>
            <th scope="col">Conflict</th>
          </tr>
        </thead>
        <tbody>
          {points.map((point) => (
            <tr key={point.publish_time_utc} className={point.eligible_at_decision ? "" : "row-later"}>
              <td>{point.publish_time_utc}</td>
              <td className="numeric">{point.generation_mw === null ? "Missing" : `${formatCount(point.generation_mw)} MW`}</td>
              <td>{point.eligible_at_decision ? "Available" : "After cutoff"}</td>
              <td>{point.selected_for_decision ? "Selected" : "Not selected"}</td>
              <td>
                {point.selected_for_latest_available
                  ? point.eligible_at_decision
                    ? "Newest, available at the cutoff"
                    : "Newest, not available at the cutoff"
                  : "No"}
              </td>
              <td>{point.conflict ? "Not averaged" : "No"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
