import { describe, expect, it } from "vitest";
import { ApiRequestError, messageFrom } from "./http";
import { ShapeError } from "./shape";
import { parseSeries, parseSummary, parseVintages } from "./guards";
import { buildWindowSearch } from "./studyClient";
import { formatMeasuredMw, rangeWindowError } from "../format/display";

const definitions = {
  signed_error: "signed",
  mean_error: "bias",
  mean_absolute_error: "mae",
  root_mean_squared_error: "rmse",
  weighted_absolute_percentage_error: "wape",
  coverage_percent: "coverage",
  mape: "not_calculated",
  reference: "docs/ANALYTICS.md",
};

function window() {
  return {
    delivery_start: "2026-01-16",
    delivery_end: "2026-01-16",
    decision_timezone: "Europe/London",
    decision_cutoff_local: "09:00",
    cutoff_basis: "pilot_assumption",
    cutoff_convention: "previous calendar day",
    settlement_period: null,
    generation_unit: "MW",
    error_unit: "MW",
    null_generation_meaning: "JSON null is a missing measurement.",
    metric_definitions: definitions,
  };
}

function provenance() {
  return {
    fetched_at_utc: "2026-10-25T21:23:43Z",
    live_elexon_request: false,
    refresh_strategy: "Read the cache.",
    data_attribution: "Contains BMRS data.",
    data_licence_url: "https://example.test/licence",
    ingestion_coverage_status: "complete",
    ingestion_limitations: ["No cursor is documented."],
    cache_actual_rows: 2,
    cache_forecast_rows: 2,
    study_window_matches_request_settings: true,
  };
}

function metrics(matched: number) {
  if (matched === 0) {
    return {
      matched_interval_count: 0,
      mean_error_mw: null,
      mean_absolute_error_mw: null,
      root_mean_squared_error_mw: null,
      weighted_absolute_percentage_error_percent: null,
      wape_status: "not_applicable_no_matches",
      generation_unit: "MW",
      error_unit: "MW",
    };
  }
  return {
    matched_interval_count: matched,
    mean_error_mw: -79,
    mean_absolute_error_mw: 79,
    root_mean_squared_error_mw: 79,
    weighted_absolute_percentage_error_percent: 1.05,
    wape_status: "calculated",
    generation_unit: "MW",
    error_unit: "MW",
  };
}

function coverage(matched: number, missingForecast: number) {
  return {
    denominator_definition: "Requested half-hours.",
    denominator_interval_count: matched + missingForecast,
    matched_interval_count: matched,
    intervals_without_usable_forecast: missingForecast,
    intervals_without_usable_actual: 0,
    coverage_percent: matched + missingForecast === 0 ? null : (100 * matched) / (matched + missingForecast),
    status_counts: {
      matched,
      missing_forecast: missingForecast,
      missing_actual: 0,
      missing_both: 0,
      excluded_conflicting_forecast: 0,
      excluded_conflicting_actual: 0,
      excluded_conflicting_records: 0,
    },
  };
}

function score(role: "decision_time" | "latest_available") {
  return {
    role,
    available_to_purchaser: role === "decision_time",
    description: role === "decision_time" ? "Decision-time score." : "Not available to the purchaser.",
    metrics: metrics(1),
    coverage: coverage(1, 1),
    distinct_selected_publish_times_utc: ["2026-01-15T07:30:00Z"],
    selections_after_cutoff: role === "decision_time" ? 0 : 1,
  };
}

describe("api failures", () => {
  it("keeps a cache failure as an error and does not describe it as zero generation", () => {
    const failure = new ApiRequestError(
      409,
      "cache_missing",
      "No study cache. A missing cache is not an empty generation series.",
    );
    const message = messageFrom(failure);
    expect(message).toContain("HTTP 409, cache_missing");
    expect(message).not.toContain("0 MW");
  });
});

describe("study query strings", () => {
  it("keeps a delivery date and a date range apart", () => {
    expect(buildWindowSearch({ deliveryDate: "2026-01-16", decisionCutoffLocal: "09:00" })).toBe(
      "?delivery_date=2026-01-16&decision_cutoff_local=09%3A00",
    );
    expect(() =>
      buildWindowSearch({ deliveryDate: "2026-01-16", dateFrom: "2026-01-01" }),
    ).toThrow(/not both/);
  });

  it("rejects a reversed date range before a request is sent", () => {
    expect(rangeWindowError("2026-01-20", "2026-01-10", "2026-01-01", "2026-01-31")).toMatch(
      /on or before/,
    );
  });
});

describe("response guards", () => {
  it("accepts a decision-time summary and rejects a leaked latest-available flag", () => {
    const summary = {
      window: window(),
      provenance: provenance(),
      window_note: "One day.",
      primary: score("decision_time"),
      latest_available: score("latest_available"),
      trading_recommendation: "not_provided",
    };
    expect(parseSummary(summary).primary.selections_after_cutoff).toBe(0);
    expect(() =>
      parseSummary({
        ...summary,
        latest_available: { ...score("latest_available"), available_to_purchaser: true },
      }),
    ).toThrow(ShapeError);
  });

  it("treats a missing forecast as missing even when generation would otherwise be zero", () => {
    const series = {
      window: window(),
      provenance: provenance(),
      window_note: "Two intervals.",
      comparison: "decision_time",
      available_to_purchaser: true,
      interval_count: 2,
      truncated: false,
      trading_recommendation: "not_provided",
      intervals: [
        {
          start_time_utc: "2026-01-16T00:00:00Z",
          delivery_date: "2026-01-16",
          settlement_period: 1,
          local_start_time: "00:00",
          cutoff_utc: "2026-01-15T09:00:00Z",
          actual_generation_mw: 0,
          actual_measurement: "measured",
          selected_publish_time_utc: "2026-01-15T07:30:00Z",
          forecast_generation_mw: 10,
          forecast_measurement: "measured",
          signed_error_mw: 10,
          absolute_error_mw: 10,
          match_status: "matched",
          generation_unit: "MW",
          error_unit: "MW",
        },
        {
          start_time_utc: "2026-01-16T00:30:00Z",
          delivery_date: "2026-01-16",
          settlement_period: 2,
          local_start_time: "00:30",
          cutoff_utc: "2026-01-15T09:00:00Z",
          actual_generation_mw: 0,
          actual_measurement: "measured",
          selected_publish_time_utc: null,
          forecast_generation_mw: null,
          forecast_measurement: "missing",
          signed_error_mw: null,
          absolute_error_mw: null,
          match_status: "missing_forecast",
          generation_unit: "MW",
          error_unit: "MW",
        },
      ],
    };
    const parsed = parseSeries(series);
    expect(formatMeasuredMw(parsed.intervals[0].actual_generation_mw, "measured")).toBe("0 MW");
    expect(formatMeasuredMw(parsed.intervals[1].forecast_generation_mw, "missing")).toBe("Missing");
    expect(() =>
      parseSeries({
        ...series,
        intervals: [
          series.intervals[0],
          { ...series.intervals[1], forecast_generation_mw: 0, forecast_measurement: "missing" },
        ],
      }),
    ).toThrow(ShapeError);
  });

  it("rejects a post-cutoff publication marked as the decision forecast", () => {
    expect(() =>
      parseVintages({
        window: window(),
        provenance: provenance(),
        primary_score_uses_only_eligible_points: true,
        trading_recommendation: "not_provided",
        evolution: {
          target_start_time_utc: "2026-01-16T00:00:00Z",
          delivery_date: "2026-01-16",
          cutoff_utc: "2026-01-15T09:00:00Z",
          outside_scored_grid: false,
          note: "Later points are excluded.",
          points: [
            {
              publish_time_utc: "2026-01-15T09:30:00Z",
              generation_mw: 20,
              eligible_at_decision: false,
              selected_for_decision: true,
              selected_for_latest_available: true,
              conflict: false,
            },
          ],
        },
      }),
    ).toThrow(/selected_for_decision/);
  });
});
