import type { ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { SeriesInterval, SeriesResponse } from "../api/types";
import { formatCount, formatMatchStatus } from "../format/display";

interface ErrorRow {
  label: string;
  signedErrorMw: number | null;
  absoluteErrorMw: number | null;
  interval: SeriesInterval;
}

export function ErrorCharts({ series }: { series: SeriesResponse }) {
  const multiDay = series.window.delivery_start !== series.window.delivery_end;
  const rows: ErrorRow[] = series.intervals.map((interval) => ({
    label: multiDay ? `${interval.delivery_date.slice(5)} ${interval.local_start_time}` : interval.local_start_time,
    signedErrorMw: interval.signed_error_mw,
    absoluteErrorMw: interval.absolute_error_mw,
    interval,
  }));
  const anyError = rows.some((row) => row.signedErrorMw !== null);

  if (!anyError) {
    return (
      <p className="state">
        No matched intervals in this window, so signed and absolute error are not plotted. Unmatched
        intervals are not shown as zero error.
      </p>
    );
  }

  return (
    <div className="chart-pair">
      <ErrorFigure
        label="Signed error"
        caption="Signed error is forecast minus actual, in MW, on matched intervals only. A gap is an unmatched interval, not a zero error."
        rows={rows}
        dataKey="signedErrorMw"
        colorFor={(value) => (value !== null && value < 0 ? "#1d6b54" : "#8c3a3a")}
      />
      <ErrorFigure
        label="Absolute error"
        caption="Absolute error is the size of the miss, in MW, on matched intervals only."
        rows={rows}
        dataKey="absoluteErrorMw"
        colorFor={() => "#1f4e79"}
      />
    </div>
  );
}

function ErrorFigure({
  label,
  caption,
  rows,
  dataKey,
  colorFor,
}: {
  label: string;
  caption: string;
  rows: ErrorRow[];
  dataKey: "signedErrorMw" | "absoluteErrorMw";
  colorFor: (value: number | null) => string;
}) {
  return (
    <figure className="chart" aria-label={label}>
      <h3>{label}</h3>
      <div className="chart-canvas chart-canvas-short">
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 640, height: 220 }}>
          <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#e1e7ee" vertical={false} />
            <XAxis dataKey="label" minTickGap={28} tick={{ fontSize: 11, fill: "#5c6b7a" }} />
            <YAxis
              width={56}
              tickFormatter={(value: number) => formatCount(value)}
              tick={{ fontSize: 11, fill: "#5c6b7a" }}
            />
            <Tooltip content={(props) => <ErrorTip {...props} />} filterNull={false} />
            <Bar dataKey={dataKey} name={label} isAnimationActive={false}>
              {rows.map((row) => (
                <Cell key={row.interval.start_time_utc} fill={colorFor(row[dataKey])} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

function ErrorTip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: ErrorRow }>;
}): ReactNode {
  const row = payload?.[0]?.payload;
  if (!active || !row) {
    return null;
  }
  const interval = row.interval;
  return (
    <div className="chart-tip">
      <p className="chart-tip-title">
        {interval.delivery_date} {interval.local_start_time}
      </p>
      <dl>
        <div>
          <dt>Signed error</dt>
          <dd>{interval.signed_error_mw === null ? "Not calculated" : `${formatCount(interval.signed_error_mw)} MW`}</dd>
        </div>
        <div>
          <dt>Absolute error</dt>
          <dd>{interval.absolute_error_mw === null ? "Not calculated" : `${formatCount(interval.absolute_error_mw)} MW`}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{formatMatchStatus(interval.match_status)}</dd>
        </div>
      </dl>
    </div>
  );
}
