import { parseSeries, parseSummary } from "../api/guards";
import { seriesPath, summaryPath } from "../api/studyClient";
import type { WindowRequest } from "../api/studyClient";
import { ErrorCharts } from "../components/ErrorCharts";
import { GenerationChart } from "../components/GenerationChart";
import { PanelState } from "../components/PanelState";
import { ProvenanceNote } from "../components/ProvenanceNote";
import { ScoreCards } from "../components/ScoreCards";
import { SettlementTable } from "../components/SettlementTable";
import { rangeWindowError, plainLabel } from "../format/display";
import { useGet } from "../hooks/useGet";

export function AnalysisView({
  deliveryDate,
  cutoffLocal,
  studyStart,
  studyEnd,
  analysisMode,
  dateFrom,
  dateTo,
  onAnalysisMode,
  onDateFrom,
  onDateTo,
}: {
  deliveryDate: string;
  cutoffLocal: string;
  studyStart: string;
  studyEnd: string;
  analysisMode: "day" | "range";
  dateFrom: string;
  dateTo: string;
  onAnalysisMode: (mode: "day" | "range") => void;
  onDateFrom: (value: string) => void;
  onDateTo: (value: string) => void;
}) {
  const rangeError = analysisMode === "range" ? rangeWindowError(dateFrom, dateTo, studyStart, studyEnd) : null;
  const request: WindowRequest | null =
    analysisMode === "day"
      ? { deliveryDate, decisionCutoffLocal: cutoffLocal }
      : rangeError
        ? null
        : { dateFrom, dateTo, decisionCutoffLocal: cutoffLocal };
  const summary = useGet(request ? summaryPath(request) : null, parseSummary);
  const series = useGet(request ? seriesPath(request) : null, parseSeries);

  return (
    <div className="view">
      <section>
        <h2>Forecast analysis</h2>
        <fieldset className="window-choice">
          <legend>Analysis window</legend>
          <label className="choice">
            <input
              type="radio"
              name="analysis-window"
              checked={analysisMode === "day"}
              onChange={() => onAnalysisMode("day")}
            />
            Selected delivery day ({deliveryDate})
          </label>
          <label className="choice">
            <input
              type="radio"
              name="analysis-window"
              checked={analysisMode === "range"}
              onChange={() => onAnalysisMode("range")}
            />
            Date range
          </label>
          {analysisMode === "range" ? (
            <div className="range-fields">
              <label className="field">
                From
                <input type="date" min={studyStart} max={studyEnd} value={dateFrom} onChange={(event) => onDateFrom(event.target.value)} />
              </label>
              <label className="field">
                To
                <input type="date" min={studyStart} max={studyEnd} value={dateTo} onChange={(event) => onDateTo(event.target.value)} />
              </label>
            </div>
          ) : null}
        </fieldset>
        {rangeError ? <p className="state state-error" role="alert">{rangeError}</p> : null}
      </section>

      {rangeError ? null : (
        <>
      <PanelState
        status={summary.status}
        errorMessage={summary.errorMessage}
        onRetry={summary.retry}
        loadingLabel="Loading the decision-time score for this window."
      >
        {summary.data ? (
          <section>
            <p className="note">
              {summary.data.window.delivery_start} through {summary.data.window.delivery_end}. Cutoff{" "}
              {summary.data.window.decision_cutoff_local} {summary.data.window.decision_timezone}. Basis:{" "}
              {plainLabel(summary.data.window.cutoff_basis)}. {summary.data.window_note}
            </p>
            <ScoreCards score={summary.data.primary} definitions={summary.data.window.metric_definitions} />
            <ProvenanceNote provenance={summary.data.provenance} />
          </section>
        ) : null}
      </PanelState>

      <PanelState
        status={series.status}
        errorMessage={series.errorMessage}
        onRetry={series.retry}
        loadingLabel="Loading the half-hourly series."
      >
        {series.data ? (
          series.data.interval_count === 0 ? (
            <p className="state">{series.data.window_note}</p>
          ) : (
            <section>
              <h3>Half-hourly forecast and actual</h3>
              <GenerationChart series={series.data} />
              <ErrorCharts series={series.data} />
              <SettlementTable series={series.data} />
            </section>
          )
        ) : null}
      </PanelState>
        </>
      )}
    </div>
  );
}
