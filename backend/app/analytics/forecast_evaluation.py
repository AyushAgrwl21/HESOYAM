"""Decision-time forecast evaluation.

The function scores rows it is given. It does not call Elexon and it does not
create a generation value for a period the forecast or the actual does not cover.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.analytics.cutoff_policy import (
    COVERAGE_DENOMINATOR_DEFINITION,
    CUTOFF_CONVENTION,
    GENERATION_UNIT,
    PILOT_CUTOFF_BASIS,
    decision_cutoff_utc,
    parse_cutoff_local,
)
from app.analytics.error_metrics import calculate_error_metrics
from app.analytics.vintage_selection import (
    SCORING_DEDUPLICATION_POLICY,
    ForecastIndex,
    SelectedPublication,
    candidate_from_generations,
    index_forecasts,
    select_latest_publication,
)
from app.data_access.record_parsing import WindActualRecord, WindForecastRecord
from app.data_access.study_window import expected_half_hour_starts
from app.data_access.timestamps import parse_utc_timestamp
from app.schemas.evaluation import (
    ComparisonBlock,
    ComparisonRole,
    CoverageReport,
    CoverageStatusCounts,
    DayAccuracy,
    DecisionEvaluation,
    ErrorMetrics,
    InputAccounting,
    IntervalScore,
    MatchStatus,
    ScoringDuplicateReport,
    SettlementPeriodAccuracy,
    VintageEvolution,
    VintagePoint,
)

PRIMARY_DESCRIPTION = (
    "Primary decision-time score. For each delivery date the cutoff is the "
    "configured local time on the previous calendar day. Each target uses the "
    "latest WINDFOR publishTime at or before that cutoff. A later publication "
    "is not an input to these metrics."
)
LATEST_AVAILABLE_DESCRIPTION = (
    "Latest-available comparison. For each target this is the newest WINDFOR "
    "publication in the supplied rows, including publications after the "
    "purchasing cutoff and after delivery. This was not information available "
    "to the original purchaser, and it is not the decision-time score."
)
VINTAGE_NOTE = (
    "Points with eligible_at_decision false were published after this target's "
    "cutoff. They are shown so that exclusion can be checked. They are not "
    "inputs to the primary metrics. selected_for_latest_available marks the "
    "newest supplied publication, which the purchaser may not have had."
)


@dataclass(frozen=True)
class _GridSlot:
    start_time_utc: str
    delivery_date: date
    settlement_period: int
    local_start_time: str
    cutoff_utc: datetime


@dataclass(frozen=True)
class _ActualIndex:
    by_start_time: dict[str, SelectedPublication]
    identical_copies_collapsed: int
    conflicting_keys: int
    conflicting_rows: int
    rows_outside_study: int
    misaligned_rows: int


def evaluate_decision_time_forecast(
    actual_generation_rows: list[WindActualRecord],
    forecast_generation_rows: list[WindForecastRecord],
    *,
    study_start: date,
    study_end: date,
    decision_timezone: str = "Europe/London",
    decision_cutoff_local: str = "09:00",
    vintage_target_start_time_utc: str | None = None,
) -> DecisionEvaluation:
    """Score the forecast available at each delivery date's cutoff.

    The latest-available block uses the same rows without the cutoff. Its
    available_to_purchaser flag is false.
    """
    cutoff_local = _require_cutoff_local(decision_cutoff_local)
    timezone_name = _require_timezone(decision_timezone)
    if study_start > study_end:
        raise ValueError(
            "study_start must be on or before study_end. "
            f"Received {study_start.isoformat()} through {study_end.isoformat()}."
        )

    grid = _build_study_grid(study_start, study_end, timezone_name, cutoff_local)
    grid_by_start = {slot.start_time_utc: slot for slot in grid}
    actual_index = _index_actuals(actual_generation_rows, grid_by_start)
    forecast_index = index_forecasts(forecast_generation_rows)
    forecast_rows_outside_study = sum(
        1
        for record in forecast_generation_rows
        if record.start_time_utc not in grid_by_start
    )

    primary_series = [
        _score_slot(
            slot,
            actual_index.by_start_time.get(slot.start_time_utc),
            select_latest_publication(
                forecast_index.by_start_time.get(slot.start_time_utc, {}),
                slot.cutoff_utc,
            ),
        )
        for slot in grid
    ]
    latest_series = [
        _score_slot(
            slot,
            actual_index.by_start_time.get(slot.start_time_utc),
            select_latest_publication(
                forecast_index.by_start_time.get(slot.start_time_utc, {}),
                None,
            ),
        )
        for slot in grid
    ]
    return DecisionEvaluation(
        cutoff_basis=PILOT_CUTOFF_BASIS,
        decision_timezone=timezone_name,
        decision_cutoff_local=cutoff_local,
        cutoff_convention=CUTOFF_CONVENTION,
        generation_unit=GENERATION_UNIT,
        study_start=study_start,
        study_end=study_end,
        inputs=_input_accounting(
            actual_generation_rows,
            forecast_generation_rows,
            actual_index,
            forecast_index,
            forecast_rows_outside_study,
        ),
        primary=_comparison_block(
            role="decision_time",
            available_to_purchaser=True,
            description=PRIMARY_DESCRIPTION,
            series=primary_series,
            timezone_name=timezone_name,
            cutoff_local=cutoff_local,
        ),
        latest_available=_comparison_block(
            role="latest_available",
            available_to_purchaser=False,
            description=LATEST_AVAILABLE_DESCRIPTION,
            series=latest_series,
            timezone_name=timezone_name,
            cutoff_local=cutoff_local,
        ),
        vintage_evolution=_vintage_evolution(
            vintage_target_start_time_utc,
            forecast_index,
            grid_by_start,
            timezone_name,
            cutoff_local,
        ),
    )


def _score_slot(
    slot: _GridSlot,
    actual: SelectedPublication | None,
    forecast: SelectedPublication,
) -> IntervalScore:
    actual_conflict = actual is not None and actual.conflict
    actual_generation = None if actual is None or actual_conflict else actual.generation_mw
    forecast_conflict = forecast.conflict
    forecast_generation = None if forecast_conflict else forecast.generation_mw
    actual_usable = actual_generation is not None
    forecast_usable = forecast_generation is not None
    status = _match_status(
        actual_conflict=actual_conflict,
        forecast_conflict=forecast_conflict,
        actual_usable=actual_usable,
        forecast_usable=forecast_usable,
    )
    signed_error_mw = None
    absolute_error_mw = None
    if (
        status == "matched"
        and forecast_generation is not None
        and actual_generation is not None
    ):
        signed_error_mw = forecast_generation - actual_generation
        absolute_error_mw = abs(signed_error_mw)
    return IntervalScore(
        start_time_utc=slot.start_time_utc,
        delivery_date=slot.delivery_date,
        settlement_period=slot.settlement_period,
        local_start_time=slot.local_start_time,
        cutoff_utc=slot.cutoff_utc,
        actual_generation_mw=actual_generation if actual_usable else None,
        selected_publish_time_utc=forecast.publish_time_utc,
        forecast_generation_mw=forecast_generation if forecast_usable else None,
        signed_error_mw=signed_error_mw,
        absolute_error_mw=absolute_error_mw,
        match_status=status,
    )


def _match_status(
    *,
    actual_conflict: bool,
    forecast_conflict: bool,
    actual_usable: bool,
    forecast_usable: bool,
) -> MatchStatus:
    if actual_conflict and forecast_conflict:
        return "excluded_conflicting_records"
    if actual_conflict:
        return "excluded_conflicting_actual"
    if forecast_conflict:
        return "excluded_conflicting_forecast"
    if actual_usable and forecast_usable:
        return "matched"
    if actual_usable:
        return "missing_forecast"
    if forecast_usable:
        return "missing_actual"
    return "missing_both"


def _comparison_block(
    *,
    role: ComparisonRole,
    available_to_purchaser: bool,
    description: str,
    series: list[IntervalScore],
    timezone_name: str,
    cutoff_local: str,
) -> ComparisonBlock:
    pairs = [
        (row.forecast_generation_mw, row.actual_generation_mw)
        for row in series
        if row.match_status == "matched"
        and row.forecast_generation_mw is not None
        and row.actual_generation_mw is not None
    ]
    selections_after_cutoff = sum(
        1
        for row in series
        if row.selected_publish_time_utc is not None
        and parse_utc_timestamp(row.selected_publish_time_utc, "publishTime") > row.cutoff_utc
    )
    return ComparisonBlock(
        role=role,
        available_to_purchaser=available_to_purchaser,
        description=description,
        metrics=calculate_error_metrics(pairs),
        coverage=_coverage(series),
        by_delivery_day=_accuracy_by_day(series, timezone_name, cutoff_local),
        by_settlement_period=_accuracy_by_period(series),
        distinct_selected_publish_times_utc=_selected_publish_times(series),
        selections_after_cutoff=selections_after_cutoff,
        series=series,
    )


def _coverage(series: list[IntervalScore]) -> CoverageReport:
    counts = Counter(row.match_status for row in series)
    status_counts = CoverageStatusCounts(
        matched=counts["matched"],
        missing_forecast=counts["missing_forecast"],
        missing_actual=counts["missing_actual"],
        missing_both=counts["missing_both"],
        excluded_conflicting_forecast=counts["excluded_conflicting_forecast"],
        excluded_conflicting_actual=counts["excluded_conflicting_actual"],
        excluded_conflicting_records=counts["excluded_conflicting_records"],
    )
    denominator = len(series)
    partition_total = sum(status_counts.model_dump().values())
    if partition_total != denominator:
        raise ValueError(
            "Coverage statuses do not cover the study grid. "
            f"{partition_total} statuses for {denominator} intervals."
        )
    without_forecast = sum(1 for row in series if row.forecast_generation_mw is None)
    without_actual = sum(1 for row in series if row.actual_generation_mw is None)
    coverage_percent = None
    if denominator > 0:
        coverage_percent = float(Decimal(status_counts.matched) * Decimal(100) / Decimal(denominator))
    return CoverageReport(
        denominator_definition=COVERAGE_DENOMINATOR_DEFINITION,
        denominator_interval_count=denominator,
        matched_interval_count=status_counts.matched,
        intervals_without_usable_forecast=without_forecast,
        intervals_without_usable_actual=without_actual,
        coverage_percent=coverage_percent,
        status_counts=status_counts,
    )


def _accuracy_by_day(
    series: list[IntervalScore],
    timezone_name: str,
    cutoff_local: str,
) -> list[DayAccuracy]:
    rows_by_day: dict[date, list[IntervalScore]] = defaultdict(list)
    for row in series:
        rows_by_day[row.delivery_date].append(row)
    day_reports: list[DayAccuracy] = []
    for delivery_date in sorted(rows_by_day):
        day_rows = rows_by_day[delivery_date]
        pairs = _matched_pairs(day_rows)
        day_reports.append(
            DayAccuracy(
                delivery_date=delivery_date,
                cutoff_utc=decision_cutoff_utc(delivery_date, cutoff_local, timezone_name),
                cutoff_local=cutoff_local,
                metrics=calculate_error_metrics(pairs),
                coverage=_coverage(day_rows),
                selected_publish_times_utc=_selected_publish_times(day_rows),
            )
        )
    return day_reports


def _accuracy_by_period(series: list[IntervalScore]) -> list[SettlementPeriodAccuracy]:
    rows_by_period: dict[int, list[IntervalScore]] = defaultdict(list)
    for row in series:
        rows_by_period[row.settlement_period].append(row)
    period_reports: list[SettlementPeriodAccuracy] = []
    for settlement_period in sorted(rows_by_period):
        period_rows = rows_by_period[settlement_period]
        local_times = {row.local_start_time for row in period_rows}
        local_start_time = next(iter(local_times)) if len(local_times) == 1 else None
        period_reports.append(
            SettlementPeriodAccuracy(
                settlement_period=settlement_period,
                local_start_time=local_start_time,
                metrics=calculate_error_metrics(_matched_pairs(period_rows)),
                coverage=_coverage(period_rows),
                selected_publish_times_utc=_selected_publish_times(period_rows),
            )
        )
    return period_reports


def _matched_pairs(series: list[IntervalScore]) -> list[tuple[int, int]]:
    return [
        (row.forecast_generation_mw, row.actual_generation_mw)
        for row in series
        if row.match_status == "matched"
        and row.forecast_generation_mw is not None
        and row.actual_generation_mw is not None
    ]


def _selected_publish_times(series: list[IntervalScore]) -> list[str]:
    return sorted(
        {
            row.selected_publish_time_utc
            for row in series
            if row.selected_publish_time_utc is not None
        }
    )


def _vintage_evolution(
    target_start_time_utc: str | None,
    forecast_index: ForecastIndex,
    grid_by_start: dict[str, _GridSlot],
    timezone_name: str,
    cutoff_local: str,
) -> VintageEvolution | None:
    if target_start_time_utc is None:
        return None
    target_instant = parse_utc_timestamp(target_start_time_utc, "startTime")
    normalized_target = target_instant.strftime("%Y-%m-%dT%H:%M:%SZ")
    slot = grid_by_start.get(normalized_target)
    if slot is None:
        delivery_date = target_instant.astimezone(ZoneInfo(timezone_name)).date()
        cutoff_utc = decision_cutoff_utc(delivery_date, cutoff_local, timezone_name)
        outside_scored_grid = True
        note = (
            "This target is not a settlement start in the scored window, so it is "
            f"not in the primary series. {VINTAGE_NOTE}"
        )
    else:
        delivery_date = slot.delivery_date
        cutoff_utc = slot.cutoff_utc
        outside_scored_grid = False
        note = VINTAGE_NOTE
    candidates = forecast_index.by_start_time.get(normalized_target, {})
    if not candidates:
        note = (
            "No WINDFOR row in the supplied forecasts has this startTime. "
            "No generation value was created for it. "
        ) + note
    decision_choice = select_latest_publication(candidates, cutoff_utc)
    latest_choice = select_latest_publication(candidates, None)
    points = [
        VintagePoint(
            publish_time_utc=publish_time_utc,
            generation_mw=None if candidate.conflict else candidate.generation_mw,
            eligible_at_decision=parse_utc_timestamp(publish_time_utc, "publishTime") <= cutoff_utc,
            selected_for_decision=publish_time_utc == decision_choice.publish_time_utc,
            selected_for_latest_available=publish_time_utc == latest_choice.publish_time_utc,
            conflict=candidate.conflict,
        )
        for publish_time_utc, candidate in sorted(
            candidates.items(),
            key=lambda item: parse_utc_timestamp(item[0], "publishTime"),
        )
    ]
    return VintageEvolution(
        target_start_time_utc=normalized_target,
        delivery_date=delivery_date,
        cutoff_utc=cutoff_utc,
        outside_scored_grid=outside_scored_grid,
        points=points,
        note=note,
    )


def _build_study_grid(
    study_start: date,
    study_end: date,
    timezone_name: str,
    cutoff_local: str,
) -> list[_GridSlot]:
    zone = ZoneInfo(timezone_name)
    slots: list[_GridSlot] = []
    delivery_date = study_start
    while delivery_date <= study_end:
        cutoff_utc = decision_cutoff_utc(delivery_date, cutoff_local, timezone_name)
        day_starts = expected_half_hour_starts(delivery_date, delivery_date, timezone_name)
        for period_index, start_instant in enumerate(day_starts, start=1):
            slots.append(
                _GridSlot(
                    start_time_utc=start_instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    delivery_date=delivery_date,
                    settlement_period=period_index,
                    local_start_time=start_instant.astimezone(zone).strftime("%H:%M"),
                    cutoff_utc=cutoff_utc,
                )
            )
        delivery_date += timedelta(days=1)
    return slots


def _index_actuals(
    actual_rows: list[WindActualRecord],
    grid_by_start: dict[str, _GridSlot],
) -> _ActualIndex:
    grouped_generations: dict[str, list[int | None]] = defaultdict(list)
    rows_outside_study = 0
    misaligned_rows = 0
    for record in actual_rows:
        slot = grid_by_start.get(record.start_time_utc)
        if slot is None:
            rows_outside_study += 1
            continue
        if (
            record.settlement_date != slot.delivery_date
            or record.settlement_period != slot.settlement_period
        ):
            misaligned_rows += 1
            continue
        grouped_generations[record.start_time_utc].append(record.generation_mw)

    by_start_time: dict[str, SelectedPublication] = {}
    identical_copies_collapsed = 0
    conflicting_keys = 0
    conflicting_rows = 0
    for start_time_utc, generation_values in grouped_generations.items():
        candidate = candidate_from_generations(generation_values)
        identical_copies_collapsed += candidate.identical_copies_collapsed
        if candidate.conflict:
            conflicting_keys += 1
            conflicting_rows += candidate.row_count
        by_start_time[start_time_utc] = SelectedPublication(
            publish_time_utc=None,
            generation_mw=None if candidate.conflict else candidate.generation_mw,
            conflict=candidate.conflict,
            identical_copies_collapsed=candidate.identical_copies_collapsed,
        )
    return _ActualIndex(
        by_start_time=by_start_time,
        identical_copies_collapsed=identical_copies_collapsed,
        conflicting_keys=conflicting_keys,
        conflicting_rows=conflicting_rows,
        rows_outside_study=rows_outside_study,
        misaligned_rows=misaligned_rows,
    )


def _input_accounting(
    actual_rows: list[WindActualRecord],
    forecast_rows: list[WindForecastRecord],
    actual_index: _ActualIndex,
    forecast_index: ForecastIndex,
    forecast_rows_outside_study: int,
) -> InputAccounting:
    return InputAccounting(
        actual_rows=len(actual_rows),
        forecast_rows=len(forecast_rows),
        actual_rows_outside_study=actual_index.rows_outside_study,
        forecast_rows_outside_study=forecast_rows_outside_study,
        misaligned_actual_rows=actual_index.misaligned_rows,
        duplicates=ScoringDuplicateReport(
            policy=SCORING_DEDUPLICATION_POLICY,
            identical_forecast_copies_collapsed=forecast_index.identical_copies_collapsed,
            conflicting_forecast_keys=forecast_index.conflicting_keys,
            conflicting_forecast_rows=forecast_index.conflicting_rows,
            identical_actual_copies_collapsed=actual_index.identical_copies_collapsed,
            conflicting_actual_keys=actual_index.conflicting_keys,
            conflicting_actual_rows=actual_index.conflicting_rows,
        ),
    )


def _require_cutoff_local(cutoff_local: str) -> str:
    return parse_cutoff_local(cutoff_local)


@dataclass(frozen=True)
class IntervalWindowSummary:
    """Metrics for one filtered set of settlement intervals."""

    metrics: ErrorMetrics
    coverage: CoverageReport
    by_delivery_day: list[DayAccuracy]
    by_settlement_period: list[SettlementPeriodAccuracy]
    distinct_selected_publish_times_utc: list[str]
    selections_after_cutoff: int


def summarise_scored_intervals(
    series: list[IntervalScore],
    *,
    timezone_name: str,
    cutoff_local: str,
    denominator_definition: str,
) -> IntervalWindowSummary:
    """Recompute metrics for a requested slice. Unmatched rows are not zero errors."""
    coverage = _coverage(series).model_copy(
        update={"denominator_definition": denominator_definition}
    )
    selections_after_cutoff = sum(
        1
        for row in series
        if row.selected_publish_time_utc is not None
        and parse_utc_timestamp(row.selected_publish_time_utc, "publishTime") > row.cutoff_utc
    )
    return IntervalWindowSummary(
        metrics=calculate_error_metrics(_matched_pairs(series)),
        coverage=coverage,
        by_delivery_day=_accuracy_by_day(series, timezone_name, cutoff_local),
        by_settlement_period=_accuracy_by_period(series),
        distinct_selected_publish_times_utc=_selected_publish_times(series),
        selections_after_cutoff=selections_after_cutoff,
    )


def describe_forecast_vintages(
    forecast_rows: list[WindForecastRecord],
    *,
    target_start_time_utc: str,
    study_start: date,
    study_end: date,
    decision_timezone: str,
    decision_cutoff_local: str,
) -> VintageEvolution:
    """List every supplied vintage of one target. This does not call Elexon."""
    cutoff_local = parse_cutoff_local(decision_cutoff_local)
    timezone_name = _require_timezone(decision_timezone)
    grid = _build_study_grid(study_start, study_end, timezone_name, cutoff_local)
    return _vintage_evolution(
        target_start_time_utc,
        index_forecasts(forecast_rows),
        {slot.start_time_utc: slot for slot in grid},
        timezone_name,
        cutoff_local,
    )


def _require_timezone(timezone_name: str) -> str:
    normalized_name = timezone_name.strip()
    try:
        ZoneInfo(normalized_name)
    except ZoneInfoNotFoundError as error:
        raise ValueError(
            "decision_timezone must be an IANA timezone such as Europe/London. "
            f"Received {timezone_name!r}. "
            "If that name is valid, this Python environment is missing the tzdata package."
        ) from error
    return normalized_name
