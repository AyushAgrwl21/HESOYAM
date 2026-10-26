import type { CoverageReport, MatchStatus } from "../api/types";
import { formatCount, formatCoverage, formatMatchStatus } from "../format/display";

const STATUS_FIELDS: MatchStatus[] = [
  "matched",
  "missing_forecast",
  "missing_actual",
  "missing_both",
  "excluded_conflicting_forecast",
  "excluded_conflicting_actual",
  "excluded_conflicting_records",
];

export function CoverageSummary({
  coverage,
  meaning,
}: {
  coverage: CoverageReport;
  meaning: string;
}) {
  const percent = coverage.coverage_percent;
  return (
    <section className="coverage-panel">
      <h3>Coverage and missing data</h3>
      <p>{meaning}</p>
      {percent !== null && coverage.denominator_interval_count > 0 ? (
        <div
          className="meter"
          role="meter"
          aria-valuemin={0}
          aria-valuemax={coverage.denominator_interval_count}
          aria-valuenow={coverage.matched_interval_count}
          aria-label="Matched settlement intervals"
        >
          <span style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
        </div>
      ) : (
        <p>Coverage percent was not calculated for this window.</p>
      )}
      <p className="coverage-figure">
        {formatCoverage(percent)} · {formatCount(coverage.matched_interval_count)} matched of{" "}
        {formatCount(coverage.denominator_interval_count)}
      </p>
      <ul className="counts">
        <li>Without a usable forecast: {formatCount(coverage.intervals_without_usable_forecast)}</li>
        <li>Without a usable actual: {formatCount(coverage.intervals_without_usable_actual)}</li>
        {STATUS_FIELDS.map((status) => (
          <li key={status}>
            {formatMatchStatus(status)}: {formatCount(coverage.status_counts[status])}
          </li>
        ))}
      </ul>
      <p className="note">{coverage.denominator_definition}</p>
    </section>
  );
}
