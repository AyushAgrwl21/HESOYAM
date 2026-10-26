import type { MatchStatus, WapeStatus } from "../api/types";

const integerFormat = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });
const metricFormat = new Intl.NumberFormat("en-GB", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const utcFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "UTC",
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZoneName: "short",
});

export function formatMeasuredMw(
  value: number | null,
  measurement: "measured" | "missing",
): string {
  if (measurement === "missing" || value === null) {
    return "Missing";
  }
  return `${integerFormat.format(value)} MW`;
}

export function formatMetricMw(value: number | null): string {
  if (value === null) {
    return "Not calculated";
  }
  return `${metricFormat.format(value)} MW`;
}

export function formatWape(value: number | null, status: WapeStatus): string {
  if (status !== "calculated" || value === null) {
    return status === "undefined_non_positive_actual_sum" ? "Withheld" : "Not calculated";
  }
  return `${metricFormat.format(value)}%`;
}

export function formatCoverage(value: number | null): string {
  if (value === null) {
    return "Not calculated";
  }
  return `${metricFormat.format(value)}%`;
}

export function formatCount(value: number): string {
  return integerFormat.format(value);
}

export function plainLabel(value: string): string {
  const words = value.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function formatUtc(isoTimestamp: string): string {
  const parsed = Date.parse(isoTimestamp);
  if (!Number.isFinite(parsed)) {
    return isoTimestamp;
  }
  return utcFormat.format(new Date(parsed));
}

const utcShortFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "UTC",
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export function formatUtcShort(isoOrMilliseconds: string | number): string {
  const parsed = typeof isoOrMilliseconds === "number" ? isoOrMilliseconds : Date.parse(isoOrMilliseconds);
  if (!Number.isFinite(parsed)) {
    return String(isoOrMilliseconds);
  }
  return utcShortFormat.format(new Date(parsed));
}

export function formatMapeDefinition(mape: string): string {
  return mape === "not_calculated" ? "MAPE is not calculated." : mape;
}

const MATCH_STATUS_LABELS: Record<MatchStatus, string> = {
  matched: "Matched",
  missing_forecast: "Missing forecast",
  missing_actual: "Missing actual",
  missing_both: "Missing forecast and actual",
  excluded_conflicting_forecast: "Conflicting forecast excluded",
  excluded_conflicting_actual: "Conflicting actual excluded",
  excluded_conflicting_records: "Conflicting records excluded",
};

export function formatMatchStatus(status: MatchStatus): string {
  return MATCH_STATUS_LABELS[status];
}

export function isCutoffLocal(value: string): boolean {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
}

export function midpointDate(start: string, end: string): string {
  const startUtc = Date.parse(`${start}T00:00:00Z`);
  const endUtc = Date.parse(`${end}T00:00:00Z`);
  if (!Number.isFinite(startUtc) || !Number.isFinite(endUtc)) {
    return start;
  }
  return new Date(startUtc + (endUtc - startUtc) / 2).toISOString().slice(0, 10);
}

export function dateWindowError(value: string, studyStart: string, studyEnd: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return "Choose a delivery date.";
  }
  if (value < studyStart || value > studyEnd) {
    return `Choose a date from ${studyStart} to ${studyEnd}.`;
  }
  return null;
}

export function rangeWindowError(
  dateFrom: string,
  dateTo: string,
  studyStart: string,
  studyEnd: string,
): string | null {
  const fromError = dateWindowError(dateFrom, studyStart, studyEnd);
  if (fromError) {
    return fromError;
  }
  const toError = dateWindowError(dateTo, studyStart, studyEnd);
  if (toError) {
    return toError;
  }
  if (dateFrom > dateTo) {
    return "The start date must be on or before the end date.";
  }
  const dayCount = Math.round((Date.parse(`${dateTo}T00:00:00Z`) - Date.parse(`${dateFrom}T00:00:00Z`)) / 86_400_000) + 1;
  if (dayCount > 62) {
    return "A request can cover at most 62 delivery dates.";
  }
  return null;
}
