export interface WindowRequest {
  deliveryDate?: string;
  dateFrom?: string;
  dateTo?: string;
  decisionCutoffLocal?: string;
  settlementPeriod?: number;
}

export function buildWindowSearch(request: WindowRequest): string {
  if (request.deliveryDate && (request.dateFrom || request.dateTo)) {
    throw new Error("Pass a delivery date or a date range, not both.");
  }
  const params = new URLSearchParams();
  if (request.deliveryDate) {
    params.set("delivery_date", request.deliveryDate);
  }
  if (request.dateFrom) {
    params.set("date_from", request.dateFrom);
  }
  if (request.dateTo) {
    params.set("date_to", request.dateTo);
  }
  if (request.decisionCutoffLocal) {
    params.set("decision_cutoff_local", request.decisionCutoffLocal);
  }
  if (request.settlementPeriod !== undefined) {
    params.set("settlement_period", String(request.settlementPeriod));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function summaryPath(request: WindowRequest): string {
  return `/api/v1/summary${buildWindowSearch(request)}`;
}

export function seriesPath(request: WindowRequest): string {
  return `/api/v1/series${buildWindowSearch(request)}`;
}

export function accuracyPath(request: WindowRequest): string {
  return `/api/v1/accuracy${buildWindowSearch(request)}`;
}

export function dataQualityPath(request: WindowRequest): string {
  return `/api/v1/data-quality${buildWindowSearch(request)}`;
}

export function vintagesPath(deliveryDate: string, settlementPeriod: number, cutoffLocal: string): string {
  return `/api/v1/forecast-vintages${buildWindowSearch({
    deliveryDate,
    settlementPeriod,
    decisionCutoffLocal: cutoffLocal,
  })}`;
}

