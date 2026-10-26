import { MetricTile } from "./MetricTile";
import type { MetricDefinitions, ScoreBlock } from "../api/types";
import { formatMetricMw, formatWape } from "../format/display";

export function ScoreCards({
  score,
  definitions,
}: {
  score: ScoreBlock;
  definitions: MetricDefinitions;
}) {
  const metrics = score.metrics;
  return (
    <div className="metrics">
      <MetricTile
        label="Bias"
        value={formatMetricMw(metrics.mean_error_mw)}
        detail={`${metrics.matched_interval_count} matched intervals`}
        definition={definitions.mean_error}
      />
      <MetricTile
        label="MAE"
        value={formatMetricMw(metrics.mean_absolute_error_mw)}
        detail="Mean absolute error"
        definition={definitions.mean_absolute_error}
      />
      <MetricTile
        label="RMSE"
        value={formatMetricMw(metrics.root_mean_squared_error_mw)}
        detail="Root mean squared error"
        definition={definitions.root_mean_squared_error}
      />
      <MetricTile
        label="WAPE"
        value={formatWape(metrics.weighted_absolute_percentage_error_percent, metrics.wape_status)}
        detail={wapeDetail(metrics.wape_status)}
        definition={definitions.weighted_absolute_percentage_error}
      />
    </div>
  );
}

function wapeDetail(status: ScoreBlock["metrics"]["wape_status"]): string {
  if (status === "calculated") {
    return "Weighted absolute percentage error";
  }
  if (status === "undefined_non_positive_actual_sum") {
    return "Withheld: the matched actual sum is not positive";
  }
  return "Not calculated: there are no matched intervals";
}
