import { parseAccuracy, parseSeries, parseSummary } from "../api/guards";
import { accuracyPath, seriesPath, summaryPath } from "../api/studyClient";
import type { DayAccuracy, SeriesResponse, SummaryResponse } from "../api/types";
import { CoverageSummary } from "../components/CoverageSummary";
import { GenerationChart } from "../components/GenerationChart";
import { MetricDefinitionsList } from "../components/MetricDefinitionsList";
import { MonthAccuracyChart } from "../components/MonthAccuracyChart";
import { PanelState } from "../components/PanelState";
import { ProvenanceNote } from "../components/ProvenanceNote";
import { ScoreCards } from "../components/ScoreCards";
import { SettlementTable } from "../components/SettlementTable";
import { formatCount, formatCoverage, formatMetricMw, formatUtc, formatWape, plainLabel } from "../format/display";
import { useGet } from "../hooks/useGet";

export function OverviewView({
  deliveryDate,
  cutoffLocal,
  onSelectDate,
}: {
  deliveryDate: string;
  cutoffLocal: string;
  onSelectDate: (deliveryDate: string) => void;
}) {
  const dayQuery = { deliveryDate, decisionCutoffLocal: cutoffLocal };
  const summary = useGet(summaryPath(dayQuery), parseSummary);
  const series = useGet(seriesPath(dayQuery), parseSeries);
  const month = useGet(accuracyPath({ decisionCutoffLocal: cutoffLocal }), parseAccuracy);
  const provenance = summary.data?.provenance ?? month.data?.provenance;

  return (
    <div className="view">
      <PanelState
        status={summary.status}
        errorMessage={summary.errorMessage}
        onRetry={summary.retry}
        loadingLabel={`Loading the decision-time score for ${deliveryDate}.`}
      >
        {summary.data ? <DayScore summary={summary.data} /> : null}
      </PanelState>

      <PanelState
        status={series.status}
        errorMessage={series.errorMessage}
        onRetry={series.retry}
        loadingLabel={`Loading generation for ${deliveryDate}.`}
      >
        {series.data ? <DaySeries series={series.data} /> : null}
      </PanelState>

      <section>
        <h2>Study days at this cutoff</h2>
        <PanelState
          status={month.status}
          errorMessage={month.errorMessage}
          onRetry={month.retry}
          loadingLabel="Loading the delivery-day scores."
        >
          {month.data ? (
            <>
              <p className="note">
                Decision-time MAE for {month.data.window.delivery_start} through{" "}
                {month.data.window.delivery_end} at cutoff {month.data.window.decision_cutoff_local}{" "}
                {month.data.window.decision_timezone}. This is separate from the selected day's score
                above. {month.data.window_note}
              </p>
              {month.data.by_delivery_day.length === 0 ? (
                <p className="state">No delivery days were returned.</p>
              ) : (
                <>
                  <MonthAccuracyChart
                    days={month.data.by_delivery_day}
                    selectedDate={deliveryDate}
                    onSelectDate={onSelectDate}
                  />
                  <DayTable
                    days={month.data.by_delivery_day}
                    selectedDate={deliveryDate}
                    onSelectDate={onSelectDate}
                  />
                </>
              )}
            </>
          ) : null}
        </PanelState>
      </section>
      {provenance ? <ProvenanceNote provenance={provenance} /> : null}
    </div>
  );
}

function DayScore({ summary }: { summary: SummaryResponse }) {
  const window = summary.window;
  return (
    <section>
      <h2>Selected delivery day</h2>
      <p className="note">
        {window.delivery_start} through {window.delivery_end}. Decision cutoff{" "}
        {window.decision_cutoff_local} {window.decision_timezone} on the previous calendar day.
        Basis: {plainLabel(window.cutoff_basis)}. {summary.window_note}
      </p>
      <p>{summary.primary.description}</p>
      <p>
        Available to the purchaser: {summary.primary.available_to_purchaser ? "yes" : "no"}.
        Selections after the cutoff: {formatCount(summary.primary.selections_after_cutoff)}.
      </p>
      <h3>Selected publication times</h3>
      {summary.primary.distinct_selected_publish_times_utc.length === 0 ? (
        <p>No publication was selected for this window.</p>
      ) : (
        <ul className="times">
          {summary.primary.distinct_selected_publish_times_utc.map((publishTime) => (
            <li key={publishTime}>
              {formatUtc(publishTime)}
            </li>
          ))}
        </ul>
      )}
      <ScoreCards score={summary.primary} definitions={window.metric_definitions} />
      <CoverageSummary coverage={summary.primary.coverage} meaning={window.null_generation_meaning} />
      <section className="latest">
        <h3>Latest available — not the decision-time score</h3>
        <p>{summary.latest_available.description}</p>
        <p>
          Available to the purchaser: {summary.latest_available.available_to_purchaser ? "yes" : "no"}.
          Selections after the cutoff: {formatCount(summary.latest_available.selections_after_cutoff)}.
        </p>
        <ScoreCards score={summary.latest_available} definitions={window.metric_definitions} />
      </section>
      <MetricDefinitionsList definitions={window.metric_definitions} />
      <details>
        <summary>Cutoff convention</summary>
        <p>{window.cutoff_convention}</p>
      </details>
    </section>
  );
}

function DaySeries({ series }: { series: SeriesResponse }) {
  const cutoffs = [...new Set(series.intervals.map((interval) => interval.cutoff_utc))];
  return (
    <section>
      <h2>Forecast and actual generation</h2>
      {cutoffs.length > 0 ? (
        <p className="note">
          Cutoff instants in this series: {cutoffs.map((cutoff) => formatUtc(cutoff)).join("; ")}.
        </p>
      ) : null}
      {series.interval_count === 0 ? (
        <p className="state">{series.window_note}</p>
      ) : (
        <>
          <GenerationChart series={series} />
          <details className="half-hour-table">
            <summary>Half-hour values</summary>
            <SettlementTable series={series} />
          </details>
        </>
      )}
    </section>
  );
}

function DayTable({
  days,
  selectedDate,
  onSelectDate,
}: {
  days: DayAccuracy[];
  selectedDate: string;
  onSelectDate: (deliveryDate: string) => void;
}) {
  return (
    <div className="table-wrap">
      <table>
        <caption>Decision-time results by delivery day. Choose a date to score that day above.</caption>
        <thead>
          <tr>
            <th scope="col">Delivery date</th>
            <th scope="col">MAE</th>
            <th scope="col">Bias</th>
            <th scope="col">RMSE</th>
            <th scope="col">WAPE</th>
            <th scope="col">Matched</th>
            <th scope="col">Coverage</th>
            <th scope="col">Selected publishTime</th>
          </tr>
        </thead>
        <tbody>
          {days.map((day) => (
            <tr key={day.delivery_date} className={day.delivery_date === selectedDate ? "row-selected" : ""}>
              <td>
                <button
                  type="button"
                  className="date-button"
                  aria-current={day.delivery_date === selectedDate ? "date" : undefined}
                  onClick={() => onSelectDate(day.delivery_date)}
                >
                  {day.delivery_date}
                </button>
              </td>
              <td className="numeric">{formatMetricMw(day.metrics.mean_absolute_error_mw)}</td>
              <td className="numeric">{formatMetricMw(day.metrics.mean_error_mw)}</td>
              <td className="numeric">{formatMetricMw(day.metrics.root_mean_squared_error_mw)}</td>
              <td className="numeric">
                {formatWape(day.metrics.weighted_absolute_percentage_error_percent, day.metrics.wape_status)}
              </td>
              <td className="numeric">{formatCount(day.metrics.matched_interval_count)}</td>
              <td className="numeric">{formatCoverage(day.coverage.coverage_percent)}</td>
              <td>{day.selected_publish_times_utc.join(", ") || "None"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
