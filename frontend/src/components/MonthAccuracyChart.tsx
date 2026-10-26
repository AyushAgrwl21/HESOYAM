import type { ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DayAccuracy } from "../api/types";
import { formatCount, formatCoverage, formatMetricMw } from "../format/display";

interface DayRow {
  deliveryDate: string;
  label: string;
  mae: number | null;
  bias: number | null;
  matched: number;
  coverage: number | null;
  publishTimes: string;
}

export function MonthAccuracyChart({
  days,
  selectedDate,
  onSelectDate,
}: {
  days: DayAccuracy[];
  selectedDate: string;
  onSelectDate: (deliveryDate: string) => void;
}) {
  const rows: DayRow[] = days.map((day) => ({
    deliveryDate: day.delivery_date,
    label: day.delivery_date.slice(8),
    mae: day.metrics.mean_absolute_error_mw,
    bias: day.metrics.mean_error_mw,
    matched: day.metrics.matched_interval_count,
    coverage: day.coverage.coverage_percent,
    publishTimes: day.selected_publish_times_utc.join(", ") || "None",
  }));

  return (
    <figure className="chart" aria-label="Decision-time mean absolute error by delivery day">
      <div className="chart-canvas chart-canvas-short">
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 720, height: 220 }}>
          <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="#e1e7ee" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#5c6b7a" }} />
            <YAxis width={56} tickFormatter={(value: number) => formatCount(value)} tick={{ fontSize: 11, fill: "#5c6b7a" }} />
            <Tooltip content={(props) => <DayTip {...props} />} />
            <Bar
              dataKey="mae"
              name="MAE"
              isAnimationActive={false}
              onClick={(bar) => {
                const deliveryDate = readDeliveryDate(bar);
                if (deliveryDate) {
                  onSelectDate(deliveryDate);
                }
              }}
            >
              {rows.map((row) => (
                <Cell key={row.deliveryDate} fill={row.deliveryDate === selectedDate ? "#9a5b12" : "#1f4e79"} cursor="pointer" />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption>
        Each bar is that delivery day's decision-time MAE. Select a bar, or a date in the table, to
        open that day. A missing bar means MAE was not calculated.
      </figcaption>
    </figure>
  );
}

function DayTip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: DayRow }>;
}): ReactNode {
  const row = payload?.[0]?.payload;
  if (!active || !row) {
    return null;
  }
  return (
    <div className="chart-tip">
      <p className="chart-tip-title">{row.deliveryDate}</p>
      <dl>
        <div>
          <dt>MAE</dt>
          <dd>{formatMetricMw(row.mae)}</dd>
        </div>
        <div>
          <dt>Bias</dt>
          <dd>{formatMetricMw(row.bias)}</dd>
        </div>
        <div>
          <dt>Matched</dt>
          <dd>{formatCount(row.matched)}</dd>
        </div>
        <div>
          <dt>Coverage</dt>
          <dd>{formatCoverage(row.coverage)}</dd>
        </div>
        <div>
          <dt>Selected publishTime</dt>
          <dd>{row.publishTimes}</dd>
        </div>
      </dl>
    </div>
  );
}

function readDeliveryDate(bar: unknown): string | null {
  if (typeof bar !== "object" || bar === null || !Object.hasOwn(bar, "payload")) {
    return null;
  }
  const payload = Reflect.get(bar, "payload");
  if (typeof payload !== "object" || payload === null || !Object.hasOwn(payload, "deliveryDate")) {
    return null;
  }
  const deliveryDate = Reflect.get(payload, "deliveryDate");
  return typeof deliveryDate === "string" ? deliveryDate : null;
}
