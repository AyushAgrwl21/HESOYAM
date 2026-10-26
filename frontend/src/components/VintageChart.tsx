import type { ReactNode } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { VintageEvolution, VintagePoint } from "../api/types";
import { formatCount, formatUtc, formatUtcShort } from "../format/display";

interface VintageRow {
  publishMs: number;
  eligibleMw: number | null;
  laterMw: number | null;
  point: VintagePoint;
}

export function VintageChart({ evolution }: { evolution: VintageEvolution }) {
  const rows: VintageRow[] = evolution.points.map((point) => ({
    publishMs: Date.parse(point.publish_time_utc),
    eligibleMw: point.eligible_at_decision ? point.generation_mw : null,
    laterMw: point.eligible_at_decision ? null : point.generation_mw,
    point,
  }));
  const measured = rows.flatMap((row) => [row.eligibleMw, row.laterMw]).filter((value) => value !== null);
  const cutoffMs = Date.parse(evolution.cutoff_utc);
  const selected = evolution.points.find((point) => point.selected_for_decision);
  const publishTimes = rows.map((row) => row.publishMs).filter((value) => Number.isFinite(value));
  const xValues = [...publishTimes, cutoffMs].filter((value) => Number.isFinite(value));

  if (rows.length === 0 || xValues.length === 0) {
    return <p className="state">No forecast vintages were returned for this settlement period.</p>;
  }

  const xMin = Math.min(...xValues);
  const xMax = Math.max(...xValues);
  const span = Math.max(xMax - xMin, 60 * 60 * 1000);
  const selectedMw = selected?.generation_mw ?? null;

  return (
    <figure className="chart" aria-label="Forecast vintages for the selected settlement period">
      <div className="chart-canvas">
        {measured.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 720, height: 280 }}>
            <LineChart data={rows} margin={{ top: 16, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#e1e7ee" vertical={false} />
              <XAxis
                dataKey="publishMs"
                type="number"
                domain={[xMin - span * 0.04, xMax + span * 0.04]}
                tickFormatter={(value: number) => formatUtcShort(value)}
                minTickGap={36}
                tick={{ fontSize: 11, fill: "#5c6b7a" }}
              />
              <YAxis
                width={64}
                tickFormatter={(value: number) => formatCount(value)}
                tick={{ fontSize: 11, fill: "#5c6b7a" }}
                domain={measured.some((value) => value < 0) ? ["auto", "auto"] : [0, "auto"]}
              />
              <Tooltip content={(props) => <VintageTip {...props} />} filterNull={false} />
              <ReferenceLine x={cutoffMs} stroke="#1f4e79" strokeDasharray="4 3" label={{ value: "Cutoff", fill: "#1f4e79", fontSize: 11 }} />
              {selected && selected.eligible_at_decision && selectedMw !== null ? (
                <ReferenceDot x={Date.parse(selected.publish_time_utc)} y={selectedMw} r={6} fill="#9a5b12" stroke="#1a2332" />
              ) : null}
              <Line
                type="linear"
                dataKey="eligibleMw"
                name="Available at the cutoff"
                stroke="#1d6b54"
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls={false}
                isAnimationActive={false}
              />
              <Line
                type="linear"
                dataKey="laterMw"
                name="Published after the cutoff"
                stroke="#6d7886"
                strokeDasharray="5 4"
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="state">The returned vintages have no measured generation. Missing values are not drawn as zero.</p>
        )}
      </div>
      <figcaption>
        The solid line was published at or before the cutoff and could be used for the decision. The
        dashed line was published later and is not the decision-time forecast. The marked point is the
        publication selected for the decision. {evolution.note}
      </figcaption>
      <ul className="legend">
        <li><span className="swatch swatch-eligible" /> Available at the cutoff</li>
        <li><span className="swatch swatch-later" /> Published after the cutoff</li>
      </ul>
    </figure>
  );
}

function VintageTip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: VintageRow }>;
}): ReactNode {
  const row = payload?.[0]?.payload;
  if (!active || !row) {
    return null;
  }
  const point = row.point;
  return (
    <div className="chart-tip">
      <p className="chart-tip-title">{formatUtc(point.publish_time_utc)}</p>
      <dl>
        <div>
          <dt>Generation</dt>
          <dd>{point.generation_mw === null ? "Missing" : `${formatCount(point.generation_mw)} MW`}</dd>
        </div>
        <div>
          <dt>At decision time</dt>
          <dd>{point.eligible_at_decision ? "Available" : "Published after the cutoff"}</dd>
        </div>
        <div>
          <dt>Decision forecast</dt>
          <dd>{point.selected_for_decision ? "Selected" : "Not selected"}</dd>
        </div>
        <div>
          <dt>Newest cached publication</dt>
          <dd>
            {point.selected_for_latest_available
              ? point.eligible_at_decision
                ? "Yes, and it was available at the cutoff"
                : "Yes. It was not available at the decision cutoff"
              : "No"}
          </dd>
        </div>
        <div>
          <dt>Conflict</dt>
          <dd>{point.conflict ? "Conflicting values were not averaged" : "No"}</dd>
        </div>
      </dl>
    </div>
  );
}
