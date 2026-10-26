import type { MetricDefinitions } from "../api/types";
import { formatMapeDefinition } from "../format/display";

export function MetricDefinitionsList({ definitions }: { definitions: MetricDefinitions }) {
  const rows: Array<[string, string]> = [
    ["Bias (mean error)", definitions.mean_error],
    ["MAE", definitions.mean_absolute_error],
    ["RMSE", definitions.root_mean_squared_error],
    ["WAPE", definitions.weighted_absolute_percentage_error],
    ["Signed error", definitions.signed_error],
    ["Coverage", definitions.coverage_percent],
    ["MAPE", formatMapeDefinition(definitions.mape)],
  ];
  return (
    <section>
      <h3>What each metric means</h3>
      <dl className="definitions">
        {rows.map(([label, text]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
