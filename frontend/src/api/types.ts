/** JSON shapes returned by the read API. Dates and instants arrive as strings. */

export type MatchStatus =
  | "matched"
  | "missing_forecast"
  | "missing_actual"
  | "missing_both"
  | "excluded_conflicting_forecast"
  | "excluded_conflicting_actual"
  | "excluded_conflicting_records";

export type WapeStatus =
  | "calculated"
  | "undefined_non_positive_actual_sum"
  | "not_applicable_no_matches";

export type Measurement = "measured" | "missing";

export interface MetricDefinitions {
  signed_error: string;
  mean_error: string;
  mean_absolute_error: string;
  root_mean_squared_error: string;
  weighted_absolute_percentage_error: string;
  coverage_percent: string;
  mape: string;
  reference: string;
}

export interface RequestedWindow {
  delivery_start: string;
  delivery_end: string;
  decision_timezone: string;
  decision_cutoff_local: string;
  cutoff_basis: "pilot_assumption";
  cutoff_convention: string;
  settlement_period: number | null;
  generation_unit: "MW";
  error_unit: "MW";
  null_generation_meaning: string;
  metric_definitions: MetricDefinitions;
}

export interface SourceProvenance {
  fetched_at_utc: string;
  live_elexon_request: false;
  refresh_strategy: string;
  data_attribution: string;
  data_licence_url: string;
  ingestion_coverage_status: "complete" | "incomplete";
  ingestion_limitations: string[];
  cache_actual_rows: number;
  cache_forecast_rows: number;
  study_window_matches_request_settings: boolean;
}

export interface ErrorMetrics {
  matched_interval_count: number;
  mean_error_mw: number | null;
  mean_absolute_error_mw: number | null;
  root_mean_squared_error_mw: number | null;
  weighted_absolute_percentage_error_percent: number | null;
  wape_status: WapeStatus;
  generation_unit: "MW";
  error_unit: "MW";
}

export interface CoverageStatusCounts {
  matched: number;
  missing_forecast: number;
  missing_actual: number;
  missing_both: number;
  excluded_conflicting_forecast: number;
  excluded_conflicting_actual: number;
  excluded_conflicting_records: number;
}

export interface CoverageReport {
  denominator_definition: string;
  denominator_interval_count: number;
  matched_interval_count: number;
  intervals_without_usable_forecast: number;
  intervals_without_usable_actual: number;
  coverage_percent: number | null;
  status_counts: CoverageStatusCounts;
}

export interface ScoreBlock {
  role: "decision_time" | "latest_available";
  available_to_purchaser: boolean;
  description: string;
  metrics: ErrorMetrics;
  coverage: CoverageReport;
  distinct_selected_publish_times_utc: string[];
  selections_after_cutoff: number;
}

export interface SummaryResponse {
  window: RequestedWindow;
  provenance: SourceProvenance;
  window_note: string;
  primary: ScoreBlock;
  latest_available: ScoreBlock;
  trading_recommendation: "not_provided";
}

export interface SeriesInterval {
  start_time_utc: string;
  delivery_date: string;
  settlement_period: number;
  local_start_time: string;
  cutoff_utc: string;
  actual_generation_mw: number | null;
  actual_measurement: Measurement;
  selected_publish_time_utc: string | null;
  forecast_generation_mw: number | null;
  forecast_measurement: Measurement;
  signed_error_mw: number | null;
  absolute_error_mw: number | null;
  match_status: MatchStatus;
  generation_unit: "MW";
  error_unit: "MW";
}

export interface SeriesResponse {
  window: RequestedWindow;
  provenance: SourceProvenance;
  window_note: string;
  comparison: "decision_time";
  available_to_purchaser: true;
  interval_count: number;
  truncated: false;
  intervals: SeriesInterval[];
  trading_recommendation: "not_provided";
}

export interface DayAccuracy {
  delivery_date: string;
  cutoff_utc: string;
  cutoff_local: string;
  metrics: ErrorMetrics;
  coverage: CoverageReport;
  selected_publish_times_utc: string[];
}

export interface SettlementPeriodAccuracy {
  settlement_period: number;
  local_start_time: string | null;
  metrics: ErrorMetrics;
  coverage: CoverageReport;
  selected_publish_times_utc: string[];
}

export interface AccuracyResponse {
  window: RequestedWindow;
  provenance: SourceProvenance;
  window_note: string;
  primary: ScoreBlock;
  latest_available: ScoreBlock;
  by_delivery_day: DayAccuracy[];
  by_settlement_period: SettlementPeriodAccuracy[];
  trading_recommendation: "not_provided";
}

export interface VintagePoint {
  publish_time_utc: string;
  generation_mw: number | null;
  eligible_at_decision: boolean;
  selected_for_decision: boolean;
  selected_for_latest_available: boolean;
  conflict: boolean;
}

export interface VintageEvolution {
  target_start_time_utc: string;
  delivery_date: string;
  cutoff_utc: string;
  outside_scored_grid: boolean;
  points: VintagePoint[];
  note: string;
}

export interface VintageResponse {
  window: RequestedWindow;
  provenance: SourceProvenance;
  evolution: VintageEvolution;
  primary_score_uses_only_eligible_points: true;
  trading_recommendation: "not_provided";
}

export interface ExampleList {
  count: number;
  examples: string[];
}

export interface RetrievalQuality {
  coverage_status: "complete" | "incomplete";
  coverage_limitations: string[];
  actual_rows_retained: number;
  forecast_rows_retained: number;
  forecast_rows_outside_study_window: number;
  missing_half_hour_starts: ExampleList;
  unexpected_actual_starts: ExampleList;
  actual_duplicate_conflicts: number;
  forecast_duplicate_conflicts: number;
  null_actual_generation_rows: number;
  null_forecast_generation_rows: number;
  pagination: string;
  request_strategy: string;
}

export interface ScoringDuplicateReport {
  policy: string;
  identical_forecast_copies_collapsed: number;
  conflicting_forecast_keys: number;
  conflicting_forecast_rows: number;
  identical_actual_copies_collapsed: number;
  conflicting_actual_keys: number;
  conflicting_actual_rows: number;
}

export interface DataQualityResponse {
  window: RequestedWindow;
  provenance: SourceProvenance;
  retrieval: RetrievalQuality;
  scoring_duplicates: ScoringDuplicateReport;
  requested_window_coverage: CoverageReport;
  requested_window_note: string;
  trading_recommendation: "not_provided";
}

export interface HealthReport {
  status: "ok";
  service_name: "wind-procurement-api";
  study_start: string;
  study_end: string;
  fuel_type: "WIND";
  decision_timezone: string;
  decision_cutoff_local: string;
  cutoff_basis: "pilot_assumption";
  elexon_base_url: string;
  elexon_request_status: "not_called";
  analytics_status: "ready" | "unavailable";
  cache_status: "present" | "missing" | "unreadable";
  cache_fetched_at_utc: string | null;
  ingestion_coverage_status: "complete" | "incomplete" | null;
  openapi_url: "/openapi.json";
  docs_url: "/docs";
  data_attribution: string;
  data_licence_url: string;
}
