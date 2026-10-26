import type { ReactNode } from "react";

export function PanelState({
  status,
  errorMessage,
  onRetry,
  loadingLabel,
  children,
}: {
  status: "idle" | "loading" | "ready" | "error";
  errorMessage: string | null;
  onRetry: () => void;
  loadingLabel: string;
  children: ReactNode;
}) {
  if (status === "idle" || status === "loading") {
    return (
      <p className="state" role="status">
        {loadingLabel}
      </p>
    );
  }
  if (status === "error") {
    return (
      <div className="state state-error" role="alert">
        <p>{errorMessage ?? "The request failed."}</p>
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  }
  return children;
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="state">
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}
