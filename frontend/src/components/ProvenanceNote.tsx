import type { SourceProvenance } from "../api/types";
import { formatUtc } from "../format/display";

export function ProvenanceNote({ provenance }: { provenance: SourceProvenance }) {
  return (
    <p className="provenance">
      Cached extract fetched {formatUtc(provenance.fetched_at_utc)}.{" "}
      {provenance.live_elexon_request
        ? "This response called Elexon."
        : "This response did not call Elexon."}{" "}
      Ingestion coverage: {provenance.ingestion_coverage_status}. Study window matches the request
      settings: {provenance.study_window_matches_request_settings ? "yes" : "no"}.
    </p>
  );
}
