import { ShapeError, asRecord, requireBoolean, requireInt, requireLiteral, requireNullableFinite, requireNullableInt, requireNullableString, requireString, requireStringList } from "./shape";
import type {
  AccuracyResponse,
  CoverageReport,
  CoverageStatusCounts,
  DataQualityResponse,
  DayAccuracy,
  ErrorMetrics,
  ExampleList,
  HealthReport,
  MetricDefinitions,
  RequestedWindow,
  RetrievalQuality,
  ScoreBlock,
  ScoringDuplicateReport,
  SeriesInterval,
  SeriesResponse,
  SettlementPeriodAccuracy,
  SourceProvenance,
  SummaryResponse,
  VintageEvolution,
  VintagePoint,
  VintageResponse,
} from "./types";

const MATCH_STATUSES = [
  "matched",
  "missing_forecast",
  "missing_actual",
  "missing_both",
  "excluded_conflicting_forecast",
  "excluded_conflicting_actual",
  "excluded_conflicting_records",
] as const;

const WAPE_STATUSES = [
  "calculated",
  "undefined_non_positive_actual_sum",
  "not_applicable_no_matches",
] as const;

const METRIC_KEYS = [
  "signed_error",
  "mean_error",
  "mean_absolute_error",
  "root_mean_squared_error",
  "weighted_absolute_percentage_error",
  "coverage_percent",
  "mape",
  "reference",
] as const;

export function parseHealthReport(value: unknown): HealthReport {
  const record = asRecord(value, "health");
  return {
    status: requireLiteral(record, "status", ["ok"]),
    service_name: requireLiteral(record, "service_name", ["wind-procurement-api"]),
    study_start: requireString(record, "study_start"),
    study_end: requireString(record, "study_end"),
    fuel_type: requireLiteral(record, "fuel_type", ["WIND"]),
    decision_timezone: requireString(record, "decision_timezone"),
    decision_cutoff_local: requireString(record, "decision_cutoff_local"),
    cutoff_basis: requireLiteral(record, "cutoff_basis", ["pilot_assumption"]),
    elexon_base_url: requireString(record, "elexon_base_url"),
    elexon_request_status: requireLiteral(record, "elexon_request_status", ["not_called"]),
    analytics_status: requireLiteral(record, "analytics_status", ["ready", "unavailable"]),
    cache_status: requireLiteral(record, "cache_status", ["present", "missing", "unreadable"]),
    cache_fetched_at_utc: requireNullableString(record, "cache_fetched_at_utc"),
    ingestion_coverage_status: requireNullableLiteral(record, "ingestion_coverage_status", [
      "complete",
      "incomplete",
    ]),
    openapi_url: requireLiteral(record, "openapi_url", ["/openapi.json"]),
    docs_url: requireLiteral(record, "docs_url", ["/docs"]),
    data_attribution: requireString(record, "data_attribution"),
    data_licence_url: requireString(record, "data_licence_url"),
  };
}

export function parseSummary(value: unknown): SummaryResponse {
  const record = asRecord(value, "summary");
  return {
    window: parseWindow(record.window),
    provenance: parseProvenance(record.provenance),
    window_note: requireString(record, "window_note"),
    primary: parseScore(record.primary, "decision_time"),
    latest_available: parseScore(record.latest_available, "latest_available"),
    trading_recommendation: requireLiteral(record, "trading_recommendation", ["not_provided"]),
  };
}

export function parseSeries(value: unknown): SeriesResponse {
  const record = asRecord(value, "series");
  const intervals = requireArray(record.intervals, "intervals").map((item, index) =>
    parseInterval(item, index),
  );
  const intervalCount = requireInt(record, "interval_count");
  if (intervalCount !== intervals.length) {
    throw new ShapeError("interval_count");
  }
  return {
    window: parseWindow(record.window),
    provenance: parseProvenance(record.provenance),
    window_note: requireString(record, "window_note"),
    comparison: requireLiteral(record, "comparison", ["decision_time"]),
    available_to_purchaser: requireTrue(record, "available_to_purchaser"),
    interval_count: intervalCount,
    truncated: requireFalse(record, "truncated"),
    intervals,
    trading_recommendation: requireLiteral(record, "trading_recommendation", ["not_provided"]),
  };
}

export function parseAccuracy(value: unknown): AccuracyResponse {
  const record = asRecord(value, "accuracy");
  return {
    window: parseWindow(record.window),
    provenance: parseProvenance(record.provenance),
    window_note: requireString(record, "window_note"),
    primary: parseScore(record.primary, "decision_time"),
    latest_available: parseScore(record.latest_available, "latest_available"),
    by_delivery_day: requireArray(record.by_delivery_day, "by_delivery_day").map(parseDay),
    by_settlement_period: requireArray(record.by_settlement_period, "by_settlement_period").map(
      parsePeriod,
    ),
    trading_recommendation: requireLiteral(record, "trading_recommendation", ["not_provided"]),
  };
}

export function parseVintages(value: unknown): VintageResponse {
  const record = asRecord(value, "forecast-vintages");
  return {
    window: parseWindow(record.window),
    provenance: parseProvenance(record.provenance),
    evolution: parseEvolution(record.evolution),
    primary_score_uses_only_eligible_points: requireTrue(
      record,
      "primary_score_uses_only_eligible_points",
    ),
    trading_recommendation: requireLiteral(record, "trading_recommendation", ["not_provided"]),
  };
}

export function parseDataQuality(value: unknown): DataQualityResponse {
  const record = asRecord(value, "data-quality");
  return {
    window: parseWindow(record.window),
    provenance: parseProvenance(record.provenance),
    retrieval: parseRetrieval(record.retrieval),
    scoring_duplicates: parseDuplicates(record.scoring_duplicates),
    requested_window_coverage: parseCoverage(record.requested_window_coverage),
    requested_window_note: requireString(record, "requested_window_note"),
    trading_recommendation: requireLiteral(record, "trading_recommendation", ["not_provided"]),
  };
}

function parseWindow(value: unknown): RequestedWindow {
  const record = asRecord(value, "window");
  const settlementPeriod = requireNullableInt(record, "settlement_period");
  if (settlementPeriod !== null && (settlementPeriod < 1 || settlementPeriod > 50)) {
    throw new ShapeError("settlement_period");
  }
  return {
    delivery_start: requireString(record, "delivery_start"),
    delivery_end: requireString(record, "delivery_end"),
    decision_timezone: requireString(record, "decision_timezone"),
    decision_cutoff_local: requireString(record, "decision_cutoff_local"),
    cutoff_basis: requireLiteral(record, "cutoff_basis", ["pilot_assumption"]),
    cutoff_convention: requireString(record, "cutoff_convention"),
    settlement_period: settlementPeriod,
    generation_unit: requireLiteral(record, "generation_unit", ["MW"]),
    error_unit: requireLiteral(record, "error_unit", ["MW"]),
    null_generation_meaning: requireString(record, "null_generation_meaning"),
    metric_definitions: parseDefinitions(record.metric_definitions),
  };
}

function parseDefinitions(value: unknown): MetricDefinitions {
  const record = asRecord(value, "metric_definitions");
  const definitions = {} as MetricDefinitions;
  for (const key of METRIC_KEYS) {
    definitions[key] = requireString(record, key);
  }
  return definitions;
}

function parseProvenance(value: unknown): SourceProvenance {
  const record = asRecord(value, "provenance");
  const liveRequest = requireBoolean(record, "live_elexon_request");
  if (liveRequest) {
    throw new ShapeError("live_elexon_request");
  }
  return {
    fetched_at_utc: requireString(record, "fetched_at_utc"),
    live_elexon_request: false,
    refresh_strategy: requireString(record, "refresh_strategy"),
    data_attribution: requireString(record, "data_attribution"),
    data_licence_url: requireString(record, "data_licence_url"),
    ingestion_coverage_status: requireLiteral(record, "ingestion_coverage_status", [
      "complete",
      "incomplete",
    ]),
    ingestion_limitations: requireStringList(record.ingestion_limitations, "ingestion_limitations"),
    cache_actual_rows: requireInt(record, "cache_actual_rows"),
    cache_forecast_rows: requireInt(record, "cache_forecast_rows"),
    study_window_matches_request_settings: requireBoolean(
      record,
      "study_window_matches_request_settings",
    ),
  };
}

function parseScore(value: unknown, role: ScoreBlock["role"]): ScoreBlock {
  const record = asRecord(value, role);
  const available = requireBoolean(record, "available_to_purchaser");
  const selectionsAfterCutoff = requireInt(record, "selections_after_cutoff");
  if (role === "decision_time" && (!available || selectionsAfterCutoff !== 0)) {
    throw new ShapeError("decision_time score");
  }
  if (role === "latest_available" && available) {
    throw new ShapeError("latest_available score");
  }
  const metrics = parseMetrics(record.metrics);
  const coverage = parseCoverage(record.coverage);
  if (metrics.matched_interval_count !== coverage.matched_interval_count) {
    throw new ShapeError("matched_interval_count");
  }
  return {
    role: requireLiteral(record, "role", [role]),
    available_to_purchaser: available,
    description: requireString(record, "description"),
    metrics,
    coverage,
    distinct_selected_publish_times_utc: requireStringList(
      record.distinct_selected_publish_times_utc,
      "distinct_selected_publish_times_utc",
    ),
    selections_after_cutoff: selectionsAfterCutoff,
  };
}

function parseMetrics(value: unknown): ErrorMetrics {
  const record = asRecord(value, "metrics");
  const matched = requireInt(record, "matched_interval_count");
  const meanError = requireNullableFinite(record, "mean_error_mw");
  const meanAbsoluteError = requireNullableFinite(record, "mean_absolute_error_mw");
  const rootMeanSquaredError = requireNullableFinite(record, "root_mean_squared_error_mw");
  const wapeStatus = requireLiteral(record, "wape_status", WAPE_STATUSES);
  const wape = requireNullableFinite(record, "weighted_absolute_percentage_error_percent");
  const hasAnyErrorSummary = meanError !== null || meanAbsoluteError !== null || rootMeanSquaredError !== null;
  const hasCompleteErrorSummary = meanError !== null && meanAbsoluteError !== null && rootMeanSquaredError !== null;
  if (matched === 0 && (hasAnyErrorSummary || wapeStatus !== "not_applicable_no_matches")) {
    throw new ShapeError("wape_status");
  }
  if (matched > 0 && !hasCompleteErrorSummary) {
    throw new ShapeError("mean_absolute_error_mw");
  }
  if (wapeStatus === "calculated" && wape === null) {
    throw new ShapeError("weighted_absolute_percentage_error_percent");
  }
  if (wapeStatus !== "calculated" && wape !== null) {
    throw new ShapeError("wape_status");
  }
  return {
    matched_interval_count: matched,
    mean_error_mw: meanError,
    mean_absolute_error_mw: meanAbsoluteError,
    root_mean_squared_error_mw: rootMeanSquaredError,
    weighted_absolute_percentage_error_percent: wape,
    wape_status: wapeStatus,
    generation_unit: requireLiteral(record, "generation_unit", ["MW"]),
    error_unit: requireLiteral(record, "error_unit", ["MW"]),
  };
}

function parseCoverage(value: unknown): CoverageReport {
  const record = asRecord(value, "coverage");
  const statusCounts = parseStatusCounts(record.status_counts);
  const denominator = requireInt(record, "denominator_interval_count");
  const matched = requireInt(record, "matched_interval_count");
  const statusTotal = Object.values(statusCounts).reduce((sum, count) => sum + count, 0);
  if (statusTotal !== denominator || statusCounts.matched !== matched) {
    throw new ShapeError("status_counts");
  }
  return {
    denominator_definition: requireString(record, "denominator_definition"),
    denominator_interval_count: denominator,
    matched_interval_count: matched,
    intervals_without_usable_forecast: requireInt(record, "intervals_without_usable_forecast"),
    intervals_without_usable_actual: requireInt(record, "intervals_without_usable_actual"),
    coverage_percent: requireNullableFinite(record, "coverage_percent"),
    status_counts: statusCounts,
  };
}

function parseStatusCounts(value: unknown): CoverageStatusCounts {
  const record = asRecord(value, "status_counts");
  return {
    matched: requireInt(record, "matched"),
    missing_forecast: requireInt(record, "missing_forecast"),
    missing_actual: requireInt(record, "missing_actual"),
    missing_both: requireInt(record, "missing_both"),
    excluded_conflicting_forecast: requireInt(record, "excluded_conflicting_forecast"),
    excluded_conflicting_actual: requireInt(record, "excluded_conflicting_actual"),
    excluded_conflicting_records: requireInt(record, "excluded_conflicting_records"),
  };
}

function parseInterval(value: unknown, index: number): SeriesInterval {
  const record = asRecord(value, `intervals[${index}]`);
  const actualMw = requireNullableInt(record, "actual_generation_mw");
  const forecastMw = requireNullableInt(record, "forecast_generation_mw");
  const actualMeasurement = requireLiteral(record, "actual_measurement", ["measured", "missing"]);
  const forecastMeasurement = requireLiteral(record, "forecast_measurement", ["measured", "missing"]);
  if ((actualMeasurement === "missing") !== (actualMw === null)) {
    throw new ShapeError(`intervals[${index}].actual_measurement`);
  }
  if ((forecastMeasurement === "missing") !== (forecastMw === null)) {
    throw new ShapeError(`intervals[${index}].forecast_measurement`);
  }
  const signed = requireNullableInt(record, "signed_error_mw");
  const absolute = requireNullableInt(record, "absolute_error_mw");
  const matchStatus = requireLiteral(record, "match_status", MATCH_STATUSES);
  const settlementPeriod = requireInt(record, "settlement_period", 1);
  if (settlementPeriod > 50) {
    throw new ShapeError(`intervals[${index}].settlement_period`);
  }
  if (matchStatus === "matched") {
    if (
      actualMw === null ||
      forecastMw === null ||
      signed === null ||
      absolute === null ||
      signed !== forecastMw - actualMw ||
      absolute !== Math.abs(signed)
    ) {
      throw new ShapeError(`intervals[${index}].signed_error_mw`);
    }
  } else if (signed !== null || absolute !== null) {
    throw new ShapeError(`intervals[${index}].signed_error_mw`);
  }
  return {
    start_time_utc: requireString(record, "start_time_utc"),
    delivery_date: requireString(record, "delivery_date"),
    settlement_period: settlementPeriod,
    local_start_time: requireString(record, "local_start_time"),
    cutoff_utc: requireString(record, "cutoff_utc"),
    actual_generation_mw: actualMw,
    actual_measurement: actualMeasurement,
    selected_publish_time_utc: requireNullableString(record, "selected_publish_time_utc"),
    forecast_generation_mw: forecastMw,
    forecast_measurement: forecastMeasurement,
    signed_error_mw: signed,
    absolute_error_mw: absolute,
    match_status: matchStatus,
    generation_unit: requireLiteral(record, "generation_unit", ["MW"]),
    error_unit: requireLiteral(record, "error_unit", ["MW"]),
  };
}

function parseDay(value: unknown): DayAccuracy {
  const record = asRecord(value, "by_delivery_day");
  const group = parseGroup(record);
  return {
    delivery_date: requireString(record, "delivery_date"),
    cutoff_utc: requireString(record, "cutoff_utc"),
    cutoff_local: requireString(record, "cutoff_local"),
    ...group,
  };
}

function parsePeriod(value: unknown): SettlementPeriodAccuracy {
  const record = asRecord(value, "by_settlement_period");
  const settlementPeriod = requireInt(record, "settlement_period", 1);
  if (settlementPeriod > 50) {
    throw new ShapeError("settlement_period");
  }
  return {
    settlement_period: settlementPeriod,
    local_start_time: requireNullableString(record, "local_start_time"),
    ...parseGroup(record),
  };
}

function parseGroup(record: Record<string, unknown>) {
  const metrics = parseMetrics(record.metrics);
  const coverage = parseCoverage(record.coverage);
  if (metrics.matched_interval_count !== coverage.matched_interval_count) {
    throw new ShapeError("matched_interval_count");
  }
  return {
    metrics,
    coverage,
    selected_publish_times_utc: requireStringList(
      record.selected_publish_times_utc,
      "selected_publish_times_utc",
    ),
  };
}

function parseEvolution(value: unknown): VintageEvolution {
  const record = asRecord(value, "evolution");
  const points = requireArray(record.points, "points").map(parseVintagePoint);
  const decisionPoints = points.filter((point) => point.selected_for_decision);
  const newestPoints = points.filter((point) => point.selected_for_latest_available);
  if (decisionPoints.length > 1 || newestPoints.length > 1) {
    throw new ShapeError("evolution.points");
  }
  if (decisionPoints.some((point) => !point.eligible_at_decision)) {
    throw new ShapeError("selected_for_decision");
  }
  return {
    target_start_time_utc: requireString(record, "target_start_time_utc"),
    delivery_date: requireString(record, "delivery_date"),
    cutoff_utc: requireString(record, "cutoff_utc"),
    outside_scored_grid: requireBoolean(record, "outside_scored_grid"),
    points,
    note: requireString(record, "note"),
  };
}

function parseVintagePoint(value: unknown): VintagePoint {
  const record = asRecord(value, "points");
  return {
    publish_time_utc: requireString(record, "publish_time_utc"),
    generation_mw: requireNullableInt(record, "generation_mw"),
    eligible_at_decision: requireBoolean(record, "eligible_at_decision"),
    selected_for_decision: requireBoolean(record, "selected_for_decision"),
    selected_for_latest_available: requireBoolean(record, "selected_for_latest_available"),
    conflict: requireBoolean(record, "conflict"),
  };
}

function parseRetrieval(value: unknown): RetrievalQuality {
  const record = asRecord(value, "retrieval");
  return {
    coverage_status: requireLiteral(record, "coverage_status", ["complete", "incomplete"]),
    coverage_limitations: requireStringList(record.coverage_limitations, "coverage_limitations"),
    actual_rows_retained: requireInt(record, "actual_rows_retained"),
    forecast_rows_retained: requireInt(record, "forecast_rows_retained"),
    forecast_rows_outside_study_window: requireInt(record, "forecast_rows_outside_study_window"),
    missing_half_hour_starts: parseExamples(record.missing_half_hour_starts, "missing_half_hour_starts"),
    unexpected_actual_starts: parseExamples(record.unexpected_actual_starts, "unexpected_actual_starts"),
    actual_duplicate_conflicts: requireInt(record, "actual_duplicate_conflicts"),
    forecast_duplicate_conflicts: requireInt(record, "forecast_duplicate_conflicts"),
    null_actual_generation_rows: requireInt(record, "null_actual_generation_rows"),
    null_forecast_generation_rows: requireInt(record, "null_forecast_generation_rows"),
    pagination: requireString(record, "pagination"),
    request_strategy: requireString(record, "request_strategy"),
  };
}

function parseExamples(value: unknown, label: string): ExampleList {
  const record = asRecord(value, label);
  const examples = requireStringList(record.examples, `${label}.examples`);
  const count = requireInt(record, "count");
  if (count < examples.length) {
    throw new ShapeError(`${label}.count`);
  }
  return { count, examples };
}

function parseDuplicates(value: unknown): ScoringDuplicateReport {
  const record = asRecord(value, "scoring_duplicates");
  return {
    policy: requireString(record, "policy"),
    identical_forecast_copies_collapsed: requireInt(record, "identical_forecast_copies_collapsed"),
    conflicting_forecast_keys: requireInt(record, "conflicting_forecast_keys"),
    conflicting_forecast_rows: requireInt(record, "conflicting_forecast_rows"),
    identical_actual_copies_collapsed: requireInt(record, "identical_actual_copies_collapsed"),
    conflicting_actual_keys: requireInt(record, "conflicting_actual_keys"),
    conflicting_actual_rows: requireInt(record, "conflicting_actual_rows"),
  };
}

function requireArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new ShapeError(label);
  }
  return value;
}

function requireTrue(record: Record<string, unknown>, name: string): true {
  if (requireBoolean(record, name) !== true) {
    throw new ShapeError(name);
  }
  return true;
}

function requireFalse(record: Record<string, unknown>, name: string): false {
  if (requireBoolean(record, name) !== false) {
    throw new ShapeError(name);
  }
  return false;
}

function requireNullableLiteral<T extends string>(
  record: Record<string, unknown>,
  name: string,
  expected: readonly T[],
): T | null {
  if (!Object.hasOwn(record, name)) {
    throw new ShapeError(name);
  }
  const value = record[name];
  if (value === null) {
    return null;
  }
  if (typeof value !== "string" || !expected.includes(value as T)) {
    throw new ShapeError(name);
  }
  return value as T;
}
