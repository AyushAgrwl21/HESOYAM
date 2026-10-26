import type { ReactNode } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { SeriesInterval, SeriesResponse } from "../api/types";
import { formatCount, formatMatchStatus, formatMeasuredMw, formatUtc } from "../format/display";

interface GenerationRow {
  label: string;
  actualMw: number | null;
  forecastMw: number | null;
  interval: SeriesInterval;
}

const chartMargin = { top: 12, right: 12, left: 0, bottom: 0 };

export function GenerationChart({ series }: { series: SeriesResponse }) {
  const multiDay = series.window.delivery_start !== series.window.delivery_end;
  const rows: GenerationRow[] = series.intervals.map((interval) => ({
    label: multiDay ? `${interval.delivery_date.slice(5)} ${interval.local_start_time}` : interval.local_start_time,
    actualMw: interval.actual_measurement === "measured" ? interval.actual_generation_mw : null,
    forecastMw: interval.forecast_measurement === "measured" ? interval.forecast_generation_mw : null,
    interval,
  }));
  const measured = rows.flatMap((row) => [row.actualMw, row.forecastMw]).filter((value) => value !== null);
  const anyMeasured = measured.length > 0;

  return (
    <figure className="chart" aria-label="Decision-time wind forecast and actual generation">
      <div className="chart-canvas">
        {anyMeasured ? (
          <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 720, height: 280 }}>
            <LineChart data={rows} margin={chartMargin}>
              <CartesianGrid stroke="#e1e7ee" vertical={false} />
              <XAxis dataKey="label" minTickGap={28} tick={{ fontSize: 11, fill: "#5c6b7a" }} />
              <YAxis
                tickFormatter={(value: number) => formatCount(value)}
                width={64}
                tick={{ fontSize: 11, fill: "#5c6b7a" }}
                domain={mwDomain(measured)}
                label={{ value: series.window.generation_unit, angle: -90, position: "insideLeft", fill: "#5c6b7a" }}
              />
              <Tooltip content={(props) => <GenerationTip {...props} />} filterNull={false} />
              <Line
                type="linear"
                dataKey="actualMw"
                name="Actual generation"
                stroke="#1f4e79"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
              <Line
                type="linear"
                dataKey="forecastMw"
                name="Decision-time forecast"
                stroke="#9a5b12"
                strokeWidth={2}
                dot={{ r: 2 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="state">No measured generation was returned for this window.</p>
        )}
      </div>
      <figcaption>
        Actuals are FUELHH wind. The forecast points are the decision-time WINDFOR value. A gap between
        points is a missing measurement, not zero generation.
      </figcaption>
      <ul className="legend">
        <li><span className="swatch swatch-actual" /> Actual generation</li>
        <li><span className="swatch swatch-forecast" /> Decision-time forecast</li>
      </ul>
    </figure>
  );
}

function GenerationTip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: GenerationRow }>;
}): ReactNode {
  const row = payload?.[0]?.payload;
  if (!active || !row) {
    return null;
  }
  const interval = row.interval;
  return (
    <div className="chart-tip">
      <p className="chart-tip-title">
        {interval.delivery_date} {interval.local_start_time} · period {interval.settlement_period}
      </p>
      <dl>
        <div>
          <dt>Actual</dt>
          <dd>{formatMeasuredMw(interval.actual_generation_mw, interval.actual_measurement)}</dd>
        </div>
        <div>
          <dt>Decision-time forecast</dt>
          <dd>{formatMeasuredMw(interval.forecast_generation_mw, interval.forecast_measurement)}</dd>
        </div>
        <div>
          <dt>Selected publishTime</dt>
          <dd>{interval.selected_publish_time_utc ?? "None"}</dd>
        </div>
        <div>
          <dt>Cutoff</dt>
          <dd>{formatUtc(interval.cutoff_utc)}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{formatMatchStatus(interval.match_status)}</dd>
        </div>
      </dl>
    </div>
  );
}

export function mwDomain(values: number[]): [number, number] {
  const lowest = Math.min(...values);
  const highest = Math.max(...values);
  const padding = Math.max(1, (highest - Math.min(0, lowest)) * 0.04);
  return [Math.min(0, lowest), highest + padding];
}
