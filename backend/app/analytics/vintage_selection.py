"""Choose the WINDFOR publication used for one target startTime.

The selected publication is the latest publishTime at or before the cutoff.
A null generation and a conflicting generation stay on that publication. An
earlier vintage is not substituted, and the value is not copied to another
startTime.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from app.data_access.record_parsing import WindForecastRecord
from app.data_access.timestamps import parse_utc_timestamp

SCORING_DEDUPLICATION_POLICY = (
    "Identical copies of one natural key are collapsed, and each extra copy is "
    "counted. The selected publication is the latest publishTime at or before the "
    "cutoff. If that publication has more than one generation value, the values "
    "are not averaged and no earlier publication replaces it. If its generation "
    "is null, the target is a missing forecast, not zero, and no earlier "
    "publication replaces it. The selected publishTime is still reported."
)


@dataclass(frozen=True)
class PublicationCandidate:
    """One publishTime at one startTime after identical copies are collapsed."""

    generation_mw: int | None
    conflict: bool
    identical_copies_collapsed: int
    row_count: int


@dataclass(frozen=True)
class ForecastIndex:
    """Forecasts grouped by target startTime, plus duplicate counts."""

    by_start_time: dict[str, dict[str, PublicationCandidate]]
    identical_copies_collapsed: int
    conflicting_keys: int
    conflicting_rows: int
    null_generation_keys: int


@dataclass(frozen=True)
class SelectedPublication:
    """The publication the rule chose, or an empty choice when none was eligible."""

    publish_time_utc: str | None
    generation_mw: int | None
    conflict: bool
    identical_copies_collapsed: int


def index_forecasts(forecast_rows: list[WindForecastRecord]) -> ForecastIndex:
    """Group forecast rows by startTime and publishTime."""
    grouped_generations: dict[str, dict[str, list[int | None]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for record in forecast_rows:
        grouped_generations[record.start_time_utc][record.publish_time_utc].append(
            record.generation_mw
        )

    by_start_time: dict[str, dict[str, PublicationCandidate]] = {}
    identical_copies_collapsed = 0
    conflicting_keys = 0
    conflicting_rows = 0
    null_generation_keys = 0
    for start_time_utc, publications in grouped_generations.items():
        candidates: dict[str, PublicationCandidate] = {}
        for publish_time_utc, generation_values in publications.items():
            candidate = candidate_from_generations(generation_values)
            candidates[publish_time_utc] = candidate
            identical_copies_collapsed += candidate.identical_copies_collapsed
            if candidate.conflict:
                conflicting_keys += 1
                conflicting_rows += candidate.row_count
            elif candidate.generation_mw is None:
                null_generation_keys += 1
        by_start_time[start_time_utc] = candidates
    return ForecastIndex(
        by_start_time=by_start_time,
        identical_copies_collapsed=identical_copies_collapsed,
        conflicting_keys=conflicting_keys,
        conflicting_rows=conflicting_rows,
        null_generation_keys=null_generation_keys,
    )


def select_latest_publication(
    candidates: dict[str, PublicationCandidate],
    cutoff_utc: datetime | None,
) -> SelectedPublication:
    """Pick the newest publication. cutoff_utc None means no purchasing bound.

    A cutoff of None is only for the latest-available comparison. Passing None
    into the decision-time path would admit every vintage.
    """
    eligible: list[tuple[datetime, str, PublicationCandidate]] = []
    for publish_time_utc, candidate in candidates.items():
        publish_instant = parse_utc_timestamp(publish_time_utc, "publishTime")
        if cutoff_utc is not None and publish_instant > cutoff_utc:
            continue
        eligible.append((publish_instant, publish_time_utc, candidate))
    if not eligible:
        return SelectedPublication(
            publish_time_utc=None,
            generation_mw=None,
            conflict=False,
            identical_copies_collapsed=0,
        )
    _, publish_time_utc, candidate = max(eligible, key=lambda item: item[0])
    if candidate.conflict:
        return SelectedPublication(
            publish_time_utc=publish_time_utc,
            generation_mw=None,
            conflict=True,
            identical_copies_collapsed=candidate.identical_copies_collapsed,
        )
    return SelectedPublication(
        publish_time_utc=publish_time_utc,
        generation_mw=candidate.generation_mw,
        conflict=False,
        identical_copies_collapsed=candidate.identical_copies_collapsed,
    )


def candidate_from_generations(generation_values: list[int | None]) -> PublicationCandidate:
    distinct_values = set(generation_values)
    identical_copies_collapsed = len(generation_values) - len(distinct_values)
    conflict = len(distinct_values) > 1
    generation_mw = None if conflict else generation_values[0]
    return PublicationCandidate(
        generation_mw=generation_mw,
        conflict=conflict,
        identical_copies_collapsed=identical_copies_collapsed,
        row_count=len(generation_values),
    )
