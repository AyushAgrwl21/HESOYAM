import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { parseHealthReport } from "./api/guards";
import type { HealthReport } from "./api/types";
import { dateWindowError, formatUtc, isCutoffLocal, midpointDate, plainLabel } from "./format/display";
import { useGet } from "./hooks/useGet";
import { QualityView } from "./views/QualityView";

const OverviewView = lazy(() =>
  import("./views/OverviewView").then((module) => ({ default: module.OverviewView })),
);
const AnalysisView = lazy(() =>
  import("./views/AnalysisView").then((module) => ({ default: module.AnalysisView })),
);
const HistoryView = lazy(() =>
  import("./views/HistoryView").then((module) => ({ default: module.HistoryView })),
);

type ViewId = "overview" | "analysis" | "history" | "quality";

const VIEWS: Array<{ id: ViewId; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "analysis", label: "Forecast analysis" },
  { id: "history", label: "Forecast history" },
  { id: "quality", label: "Data quality" },
];

export function App() {
  const health = useGet("/api/health", parseHealthReport);
  const initialQuery = readDashboardQuery();
  const [view, setView] = useState<ViewId>(initialQuery.view);
  const [deliveryDate, setDeliveryDate] = useState<string | null>(initialQuery.deliveryDate);
  const [cutoffLocal, setCutoffLocal] = useState<string | null>(initialQuery.cutoffLocal);
  const [dateFrom, setDateFrom] = useState<string | null>(initialQuery.dateFrom ?? initialQuery.deliveryDate);
  const [dateTo, setDateTo] = useState<string | null>(initialQuery.dateTo ?? initialQuery.deliveryDate);
  const [analysisMode, setAnalysisMode] = useState<"day" | "range">(initialQuery.analysisMode);
  const [settlementPeriod, setSettlementPeriod] = useState<number | null>(initialQuery.settlementPeriod);
  const writtenView = useRef(initialQuery.view);

  useEffect(() => {
    if (!health.data) {
      return;
    }
    const report = health.data;
    const middle = midpointDate(report.study_start, report.study_end);
    setDeliveryDate((current) => current ?? middle);
    setCutoffLocal((current) => current ?? report.decision_cutoff_local);
    setDateFrom((current) => current ?? middle);
    setDateTo((current) => current ?? middle);
  }, [health.data]);

  useEffect(() => {
    const label = VIEWS.find((item) => item.id === view)?.label ?? "Overview";
    document.title = `${label} · Wind Procurement Intelligence`;
    window.scrollTo(0, 0);
  }, [view]);

  useEffect(() => {
    if (!deliveryDate || !cutoffLocal || !dateFrom || !dateTo) {
      return;
    }
    const nextUrl = dashboardUrl({
      view,
      deliveryDate,
      cutoffLocal,
      dateFrom,
      dateTo,
      analysisMode,
      settlementPeriod,
    });
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (nextUrl === currentUrl) {
      writtenView.current = view;
      return;
    }
    if (view !== writtenView.current) {
      window.history.pushState(null, "", nextUrl);
    } else {
      window.history.replaceState(null, "", nextUrl);
    }
    writtenView.current = view;
  }, [view, deliveryDate, cutoffLocal, dateFrom, dateTo, analysisMode, settlementPeriod]);

  useEffect(() => {
    const restore = () => {
      const query = readDashboardQuery();
      writtenView.current = query.view;
      setView(query.view);
      setDeliveryDate(query.deliveryDate);
      setCutoffLocal(query.cutoffLocal);
      setDateFrom(query.dateFrom ?? query.deliveryDate);
      setDateTo(query.dateTo ?? query.deliveryDate);
      setAnalysisMode(query.analysisMode);
      setSettlementPeriod(query.settlementPeriod);
    };
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  const report = health.data;
  const cutoffError =
    cutoffLocal !== null && !isCutoffLocal(cutoffLocal)
      ? "Use a 24-hour time in HH:MM form, for example 09:00."
      : null;
  const deliveryError =
    report && deliveryDate ? dateWindowError(deliveryDate, report.study_start, report.study_end) : null;
  const studyReady =
    report !== null &&
    report.cache_status === "present" &&
    report.analytics_status === "ready" &&
    deliveryDate !== null &&
    cutoffLocal !== null &&
    dateFrom !== null &&
    dateTo !== null &&
    cutoffError === null &&
    deliveryError === null;

  return (
    <>
      <a className="skip" href="#results">
        Skip to results
      </a>
      <div className="hero">
      <header className="masthead">
        <div>
          <p className="eyebrow">GB electricity · national wind</p>
          <h1>Wind Procurement Intelligence</h1>
          <p className="scope">
            National wind generation for the configured study. Consumer demand and other supply are
            outside this pilot. This screen does not recommend a purchase or place an order.
          </p>
        </div>
        {report ? <StudyMeta report={report} /> : null}
      </header>
      </div>

      {health.status !== "ready" || !report ? (
        <main id="results">
          {health.status === "error" ? (
            <div className="state state-error" role="alert">
              <h2>The API is unavailable</h2>
              <p>{health.errorMessage}</p>
              <p>No generation or error figures are shown.</p>
              <button type="button" onClick={health.retry}>
                Retry
              </button>
            </div>
          ) : (
            <p className="state" role="status">
              Checking the study API.
            </p>
          )}
        </main>
      ) : (
        <>
      <div className="sticky-bar">
      <form
        className="controls"
        onSubmit={(event) => event.preventDefault()}
      >
            <label>
              Delivery date
              <input
                type="date"
                min={report.study_start}
                max={report.study_end}
                value={deliveryDate ?? ""}
                onChange={(event) => setDeliveryDate(event.target.value)}
              />
            </label>
            <label>
              Decision cutoff
              <input
                type="time"
                step={60}
                value={cutoffLocal ?? ""}
                aria-invalid={cutoffError !== null}
                aria-describedby={cutoffError ? "cutoff-error" : undefined}
                onChange={(event) => setCutoffLocal(event.target.value)}
              />
            </label>
            <div className="presets" role="group" aria-label="Cutoff presets">
              {cutoffPresets(report.decision_cutoff_local).map((preset) => (
                <button
                  key={preset}
                  type="button"
                  aria-pressed={cutoffLocal === preset}
                  onClick={() => setCutoffLocal(preset)}
                >
                  {preset}
                </button>
              ))}
            </div>
            <p className="control-note">
              Server default {report.decision_cutoff_local} {report.decision_timezone}. Basis{" "}
              {plainLabel(report.cutoff_basis)}.
            </p>
          </form>
          {cutoffError ? (
            <p id="cutoff-error" className="state state-error" role="alert">
              {cutoffError}
            </p>
          ) : null}
          {deliveryError ? (
            <p className="state state-error" role="alert">
              {deliveryError}
            </p>
          ) : null}

          <nav className="view-nav" aria-label="Dashboard views">
            {VIEWS.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-current={view === item.id ? "page" : undefined}
                onClick={() => setView(item.id)}
              >
                {item.label}
              </button>
            ))}
          </nav>
      </div>

          <main id="results">
            {report.cache_status !== "present" || report.analytics_status !== "ready" ? (
              <div className="state state-error" role="alert">
                <h2>Study data are unavailable</h2>
                <p>
                  Cache status: {report.cache_status}. Forecast evaluation: {report.analytics_status}.
                  {report.ingestion_coverage_status
                    ? ` Ingestion coverage: ${report.ingestion_coverage_status}.`
                    : ""}
                </p>
                <p>No generation or error figures are shown. This page does not call Elexon.</p>
                <button type="button" onClick={health.retry}>
                  Check again
                </button>
              </div>
            ) : null}
            {report.ingestion_coverage_status === "incomplete" ? (
              <p className="state state-error" role="alert">
                Ingestion coverage is incomplete. Treat the figures as a partial extract.
              </p>
            ) : null}
            {studyReady && deliveryDate && cutoffLocal && dateFrom && dateTo ? (
              <Suspense fallback={<p className="state" role="status">Loading this view.</p>}>
                {view === "overview" ? (
                  <OverviewView
                    deliveryDate={deliveryDate}
                    cutoffLocal={cutoffLocal}
                    onSelectDate={setDeliveryDate}
                  />
                ) : null}
                {view === "analysis" ? (
                  <AnalysisView
                    deliveryDate={deliveryDate}
                    cutoffLocal={cutoffLocal}
                    studyStart={report.study_start}
                    studyEnd={report.study_end}
                    analysisMode={analysisMode}
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onAnalysisMode={setAnalysisMode}
                    onDateFrom={setDateFrom}
                    onDateTo={setDateTo}
                  />
                ) : null}
                {view === "history" ? (
                  <HistoryView
                    deliveryDate={deliveryDate}
                    cutoffLocal={cutoffLocal}
                    settlementPeriod={settlementPeriod}
                    onSettlementPeriod={setSettlementPeriod}
                  />
                ) : null}
                {view === "quality" ? (
                  <QualityView deliveryDate={deliveryDate} cutoffLocal={cutoffLocal} health={report} />
                ) : null}
              </Suspense>
            ) : null}
          </main>
          <footer className="site-footer">
            <p>{report.data_attribution}</p>
            <p>
              <a href={report.data_licence_url}>BMRS data licence</a>
            </p>
          </footer>
        </>
      )}
    </>
  );
}

function StudyMeta({ report }: { report: HealthReport }) {
  return (
    <dl className="study-meta">
      <div>
        <dt>Study</dt>
        <dd>
          {report.study_start} to {report.study_end}
        </dd>
      </div>
      <div>
        <dt>Fuel</dt>
        <dd>{report.fuel_type}</dd>
      </div>
      <div>
        <dt>Cache</dt>
        <dd>
          {plainLabel(report.cache_status)}
          {report.cache_fetched_at_utc ? ` · ${formatUtc(report.cache_fetched_at_utc)}` : ""}
        </dd>
      </div>
      <div>
        <dt>Elexon request</dt>
        <dd>{plainLabel(report.elexon_request_status)}</dd>
      </div>
    </dl>
  );
}

function cutoffPresets(serverDefault: string): string[] {
  const presets = [serverDefault, "07:00", "09:00", "15:30"];
  return [...new Set(presets)];
}

interface DashboardQuery {
  view: ViewId;
  deliveryDate: string | null;
  cutoffLocal: string | null;
  dateFrom: string | null;
  dateTo: string | null;
  analysisMode: "day" | "range";
  settlementPeriod: number | null;
}

function readDashboardQuery(): DashboardQuery {
  const params = new URLSearchParams(window.location.search);
  const view = params.get("view");
  const period = params.get("period");
  const cutoff = params.get("cutoff");
  return {
    view: view === "analysis" || view === "history" || view === "quality" ? view : "overview",
    deliveryDate: calendarDate(params.get("date")),
    cutoffLocal: cutoff && isCutoffLocal(cutoff) ? cutoff : null,
    dateFrom: calendarDate(params.get("from")),
    dateTo: calendarDate(params.get("to")),
    analysisMode: params.get("range") === "1" ? "range" : "day",
    settlementPeriod: period !== null && /^\d+$/.test(period) ? Number(period) : null,
  };
}

function calendarDate(value: string | null): string | null {
  return value !== null && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null;
}

function dashboardUrl(query: {
  view: ViewId;
  deliveryDate: string;
  cutoffLocal: string;
  dateFrom: string;
  dateTo: string;
  analysisMode: "day" | "range";
  settlementPeriod: number | null;
}): string {
  const params = new URLSearchParams();
  if (query.view !== "overview") {
    params.set("view", query.view);
  }
  params.set("date", query.deliveryDate);
  params.set("cutoff", query.cutoffLocal);
  if (query.analysisMode === "range") {
    params.set("range", "1");
  }
  if (query.dateFrom !== query.deliveryDate) {
    params.set("from", query.dateFrom);
  }
  if (query.dateTo !== query.deliveryDate) {
    params.set("to", query.dateTo);
  }
  if (query.settlementPeriod !== null) {
    params.set("period", String(query.settlementPeriod));
  }
  const search = params.toString();
  return search ? `${window.location.pathname}?${search}` : window.location.pathname;
}
