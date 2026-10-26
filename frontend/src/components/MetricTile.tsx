import { useId, useState } from "react";

export function MetricTile({
  label,
  value,
  detail,
  definition,
}: {
  label: string;
  value: string;
  detail: string;
  definition: string;
}) {
  const definitionId = useId();
  const [open, setOpen] = useState(false);
  return (
    <article className="tile">
      <div className="tile-heading">
        <h3>{label}</h3>
        <button
          type="button"
          className="definition"
          aria-expanded={open}
          aria-controls={definitionId}
          onClick={() => setOpen((current) => !current)}
        >
          Definition
        </button>
      </div>
      <p className="tile-value">{value}</p>
      <p className="tile-detail">{detail}</p>
      {open ? (
        <p id={definitionId} className="definition-text">
          {definition}
        </p>
      ) : null}
    </article>
  );
}
