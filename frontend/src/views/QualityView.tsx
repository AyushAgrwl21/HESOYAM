import { useState } from "react";
import { parseDataQuality } from "../api/guards";
import { dataQualityPath } from "../api/studyClient";
import type { DataQualityResponse, ExampleList } from "../api/types";
import { CoverageSummary } from "../components/CoverageSummary";
import { MetricDefinitionsList } from "../components/MetricDefinitionsList";
import { PanelState } from "../components/PanelState";
import { ProvenanceNote } from "../components/ProvenanceNote";
import { formatCount, formatUtc, plainLabel } from "../format/display";
import { useGet } from "../hooks/useGet";
import type { HealthReport } from "../api/types";
import { apiUrl } from "../api/http";

export function QualityView({
  deliveryDate,
  cutoffLocal,
  health,
}: {
  deliveryDate: string;
  cutoffLocal: string;
  health: HealthReport;
}) {
  const [scope, setScope] = useState<"day" | "study">("day");
  const request = scope === "day" ? { deliveryDate, decisionCutoffLocal: cutoffLocal } : { decisionCutoffLocal: cutoffLocal };
  const quality = useGet(dataQualityPath(request), parseDataQuality);
  const docsOnApiOrigin = import.meta.env.VITE_API_BASE_URL ? apiUrl(health.docs_url) : null;
  const docsHref = docsOnApiOrigin ?? (import.meta.env.DEV ? null : health.docs_url);
  return (
    <div className="view">
      <section>
        <h2>Data quality and methodology</h2>
        <fieldset className="window-choice">
          <legend>Coverage window</legend>
          <label className="choice">
            <input type="radio" name="quality-scope" checked={scope === "day"} onChange={() => setScope("day")} />
            Selected delivery day ({deliveryDate})
          </label>
          <label className="choice">
            <input type="radio" name="quality-scope" checked={scope === "study"} onChange={() => setScope("study")} />
            Full configured study
          </label>
        </fieldset>
      </section>
      <PanelState
        status={quality.status}
        errorMessage={quality.errorMessage}
        onRetry={quality.retry}
        loadingLabel="Loading data quality for the cached study."
      >
        {quality.data ? <QualityReport report={quality.data} docsHref={docsHref} /> : null}
      </PanelState>
    </div>
  );
}

function QualityReport({
  report,
  docsHref,
}: {
  report: DataQualityResponse;
  docsHref: string | null;
}) {
  const retrieval = report.retrieval;
  const retrievalLimits = retrieval.coverage_limitations;
  const ingestionLimits = report.provenance.ingestion_limitations;
  const limitsMatch =
    retrievalLimits.length === ingestionLimits.length &&
    retrievalLimits.every((item, index) => item === ingestionLimits[index]);
  const paginationRepeated =
    retrievalLimits.includes(retrieval.pagination) || ingestionLimits.includes(retrieval.pagination);
  const incomplete =
    retrieval.coverage_status !== "complete" ||
    report.provenance.ingestion_coverage_status !== "complete" ||
    !report.provenance.study_window_matches_request_settings;

  return (
    <section>
      {incomplete ? (
        <div className="state state-error" role="alert">
          <p>
            The cached extract is incomplete or does not match the request settings. Retrieval
            coverage: {retrieval.coverage_status}. Ingestion coverage:{" "}
            {report.provenance.ingestion_coverage_status}. Study window matches request settings:{" "}
            {report.provenance.study_window_matches_request_settings ? "yes" : "no"}.
          </p>
        </div>
      ) : (
        <p className="state state-ok">
          Retrieval coverage is {retrieval.coverage_status}. The cached extract was fetched{" "}
          {formatUtc(report.provenance.fetched_at_utc)}.
        </p>
      )}

      <h3>Requested window</h3>
      <p className="note">{report.requested_window_note}</p>
      <CoverageSummary
        coverage={report.requested_window_coverage}
        meaning={report.window.null_generation_meaning}
      />

      <h3>Cached extract</h3>
      <dl className="definitions">
        <div>
          <dt>Freshness</dt>
          <dd>
            {formatUtc(report.provenance.fetched_at_utc)} ({report.provenance.fetched_at_utc})
          </dd>
        </div>
        <div>
          <dt>Elexon call on this read</dt>
          <dd>{report.provenance.live_elexon_request ? "Yes" : "No"}</dd>
        </div>
        <div>
          <dt>Actual rows retained</dt>
          <dd>{formatCount(retrieval.actual_rows_retained)}</dd>
        </div>
        <div>
          <dt>Forecast rows retained</dt>
          <dd>{formatCount(retrieval.forecast_rows_retained)}</dd>
        </div>
        <div>
          <dt>Forecast rows outside the study</dt>
          <dd>{formatCount(retrieval.forecast_rows_outside_study_window)}</dd>
        </div>
        <div>
          <dt>Null actual rows</dt>
          <dd>{formatCount(retrieval.null_actual_generation_rows)}</dd>
        </div>
        <div>
          <dt>Null forecast rows</dt>
          <dd>{formatCount(retrieval.null_forecast_generation_rows)}</dd>
        </div>
        <div>
          <dt>Duplicate conflicts, actuals</dt>
          <dd>{formatCount(retrieval.actual_duplicate_conflicts)}</dd>
        </div>
        <div>
          <dt>Duplicate conflicts, forecasts</dt>
          <dd>{formatCount(retrieval.forecast_duplicate_conflicts)}</dd>
        </div>
      </dl>
      <ExampleBlock title="Missing half-hour starts" list={retrieval.missing_half_hour_starts} />
      <ExampleBlock title="Unexpected actual starts" list={retrieval.unexpected_actual_starts} />
      {retrievalLimits.length > 0 ? (
        <>
          <h3>{limitsMatch ? "Retrieval and ingestion" : "Retrieval limitations"}</h3>
          <ul>
            {retrievalLimits.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </>
      ) : null}
      {!limitsMatch && ingestionLimits.length > 0 ? (
        <>
          <h3>Ingestion notes</h3>
          <ul>
            {ingestionLimits.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </>
      ) : null}
      {paginationRepeated ? null : <p className="note">{retrieval.pagination}</p>}
      <p className="note">Request strategy: {plainLabel(retrieval.request_strategy)}.</p>

      <h3>Duplicate handling while scoring</h3>
      <p>{report.scoring_duplicates.policy}</p>
      <ul className="counts">
        <li>Identical forecast copies collapsed: {formatCount(report.scoring_duplicates.identical_forecast_copies_collapsed)}</li>
        <li>Conflicting forecast keys: {formatCount(report.scoring_duplicates.conflicting_forecast_keys)}</li>
        <li>Conflicting forecast rows: {formatCount(report.scoring_duplicates.conflicting_forecast_rows)}</li>
        <li>Identical actual copies collapsed: {formatCount(report.scoring_duplicates.identical_actual_copies_collapsed)}</li>
        <li>Conflicting actual keys: {formatCount(report.scoring_duplicates.conflicting_actual_keys)}</li>
        <li>Conflicting actual rows: {formatCount(report.scoring_duplicates.conflicting_actual_rows)}</li>
      </ul>

      <h3>Decision cutoff</h3>
      <dl className="fact-rows">
        <div>
          <dt>Basis</dt>
          <dd>{plainLabel(report.window.cutoff_basis)}</dd>
        </div>
        <div>
          <dt>Clock time</dt>
          <dd>{report.window.decision_cutoff_local}</dd>
        </div>
        <div>
          <dt>Timezone</dt>
          <dd>{report.window.decision_timezone}</dd>
        </div>
        <div>
          <dt>Convention</dt>
          <dd>{report.window.cutoff_convention}</dd>
        </div>
        <div>
          <dt>Missing generation</dt>
          <dd>{report.window.null_generation_meaning}</dd>
        </div>
      </dl>
      <MetricDefinitionsList definitions={report.window.metric_definitions} />
      <h3>Refresh</h3>
      <p>{report.provenance.refresh_strategy}</p>
      {docsHref ? (
        <>
          <h3>Sources</h3>
          <p>
            <a href={docsHref}>API documentation</a>
          </p>
        </>
      ) : null}
      <ProvenanceNote provenance={report.provenance} />
    </section>
  );
}

function ExampleBlock({ title, list }: { title: string; list: ExampleList }) {
  return (
    <section>
      <h3>
        {title}: {formatCount(list.count)}
      </h3>
      {list.count === 0 ? <p>None were reported.</p> : null}
      {list.examples.length > 0 ? (
        <>
          {list.count > list.examples.length ? (
            <p className="note">
              Showing {formatCount(list.examples.length)} of {formatCount(list.count)}.
            </p>
          ) : null}
          <ul>
            {list.examples.map((example) => (
              <li key={example}>{example}</li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
