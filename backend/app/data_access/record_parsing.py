"""Parse FUELHH and WINDFOR stream rows without filling missing measurements."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.data_access.timestamps import RecordParseError, parse_utc_timestamp


class WindActualRecord(BaseModel):
    """One retained FUELHH wind row. generation_mw is null when Elexon sent null."""

    model_config = ConfigDict(frozen=True)

    dataset: str
    publish_time_utc: str
    start_time_utc: str
    settlement_date: date
    settlement_period: int
    fuel_type: Literal["WIND"]
    generation_mw: int | None

    @property
    def natural_key(self) -> tuple[str, int, str]:
        return (self.settlement_date.isoformat(), self.settlement_period, self.fuel_type)

    def duplicate_signature(self) -> tuple[object, ...]:
        return (
            self.dataset,
            self.publish_time_utc,
            self.start_time_utc,
            self.settlement_date.isoformat(),
            self.settlement_period,
            self.fuel_type,
            self.generation_mw,
        )


class WindForecastRecord(BaseModel):
    """One retained WINDFOR row. Different publish times stay as different vintages."""

    model_config = ConfigDict(frozen=True)

    dataset: str
    publish_time_utc: str
    start_time_utc: str
    generation_mw: int | None

    @property
    def natural_key(self) -> tuple[str, str]:
        return (self.publish_time_utc, self.start_time_utc)

    def duplicate_signature(self) -> tuple[object, ...]:
        return (
            self.dataset,
            self.publish_time_utc,
            self.start_time_utc,
            self.generation_mw,
        )


class ParsedStreamBatch[RecordT: WindActualRecord | WindForecastRecord]:
    """Rows accepted from one payload, plus problems that were not stored as valid rows."""

    def __init__(self) -> None:
        self.records: list[RecordT] = []
        self.malformed_reasons: list[str] = []
        self.excluded_non_wind_records: int = 0


def parse_actual_rows(raw_rows: list[object]) -> ParsedStreamBatch[WindActualRecord]:
    parsed_batch: ParsedStreamBatch[WindActualRecord] = ParsedStreamBatch()
    for row_index, raw_row in enumerate(raw_rows, start=1):
        try:
            if _fuel_type_is_present_and_not_wind(raw_row):
                parsed_batch.excluded_non_wind_records += 1
                continue
            parsed_batch.records.append(_parse_actual_row(raw_row))
        except RecordParseError as error:
            parsed_batch.malformed_reasons.append(f"FUELHH row {row_index}: {error}")
    return parsed_batch


def parse_forecast_rows(raw_rows: list[object]) -> ParsedStreamBatch[WindForecastRecord]:
    parsed_batch: ParsedStreamBatch[WindForecastRecord] = ParsedStreamBatch()
    for row_index, raw_row in enumerate(raw_rows, start=1):
        try:
            parsed_batch.records.append(_parse_forecast_row(raw_row))
        except RecordParseError as error:
            parsed_batch.malformed_reasons.append(f"WINDFOR row {row_index}: {error}")
    return parsed_batch


def _parse_actual_row(raw_row: object) -> WindActualRecord:
    row_fields = _require_object(raw_row, "FUELHH")
    settlement_period = _require_settlement_period(row_fields.get("settlementPeriod"))
    settlement_date = _require_settlement_date(row_fields.get("settlementDate"))
    fuel_type = _require_wind_fuel(row_fields.get("fuelType"))
    dataset = _require_text(row_fields.get("dataset"), "dataset")
    publish_time = parse_utc_timestamp(row_fields.get("publishTime"), "publishTime")
    start_time = parse_utc_timestamp(row_fields.get("startTime"), "startTime")
    generation_mw = _parse_generation(row_fields, "FUELHH")
    return WindActualRecord(
        dataset=dataset,
        publish_time_utc=_as_zulu(publish_time),
        start_time_utc=_as_zulu(start_time),
        settlement_date=settlement_date,
        settlement_period=settlement_period,
        fuel_type=fuel_type,
        generation_mw=generation_mw,
    )


def _parse_forecast_row(raw_row: object) -> WindForecastRecord:
    row_fields = _require_object(raw_row, "WINDFOR")
    dataset = _require_text(row_fields.get("dataset"), "dataset")
    publish_time = parse_utc_timestamp(row_fields.get("publishTime"), "publishTime")
    start_time = parse_utc_timestamp(row_fields.get("startTime"), "startTime")
    generation_mw = _parse_generation(row_fields, "WINDFOR")
    return WindForecastRecord(
        dataset=dataset,
        publish_time_utc=_as_zulu(publish_time),
        start_time_utc=_as_zulu(start_time),
        generation_mw=generation_mw,
    )


def _require_object(raw_row: object, stream_name: str) -> dict[str, object]:
    if not isinstance(raw_row, dict):
        raise RecordParseError(f"{stream_name} row must be a JSON object. Received {type(raw_row).__name__}.")
    return raw_row


def _require_text(raw_value: object, field_name: str) -> str:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise RecordParseError(f"{field_name} must be a non-empty string. Received {raw_value!r}.")
    return raw_value.strip()


def _require_settlement_date(raw_value: object) -> date:
    if not isinstance(raw_value, str):
        raise RecordParseError(f"settlementDate must be yyyy-MM-dd. Received {raw_value!r}.")
    try:
        return date.fromisoformat(raw_value)
    except ValueError as error:
        raise RecordParseError(
            f"settlementDate must be yyyy-MM-dd. Received {raw_value!r}."
        ) from error


def _require_settlement_period(raw_value: object) -> int:
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise RecordParseError(
            f"settlementPeriod must be an integer from 1 to 50. Received {raw_value!r}."
        )
    if raw_value < 1 or raw_value > 50:
        raise RecordParseError(
            f"settlementPeriod must be an integer from 1 to 50. Received {raw_value}."
        )
    return raw_value


def _require_wind_fuel(raw_value: object) -> Literal["WIND"]:
    if not isinstance(raw_value, str) or raw_value.strip().upper() != "WIND":
        raise RecordParseError(f"fuelType must be WIND. Received {raw_value!r}.")
    return "WIND"


def _fuel_type_is_present_and_not_wind(raw_row: object) -> bool:
    if not isinstance(raw_row, dict):
        return False
    raw_fuel_type = raw_row.get("fuelType")
    if not isinstance(raw_fuel_type, str):
        return False
    return raw_fuel_type.strip().upper() != "WIND"


def _parse_generation(row_fields: dict[str, object], stream_name: str) -> int | None:
    if "generation" not in row_fields:
        raise RecordParseError(f"{stream_name} row has no generation field.")
    raw_generation = row_fields["generation"]
    if raw_generation is None:
        return None
    if isinstance(raw_generation, bool) or not isinstance(raw_generation, int):
        raise RecordParseError(
            "generation must be an integer number of MW, or null when the value is missing. "
            f"Received {raw_generation!r}."
        )
    return raw_generation


def _as_zulu(timestamp_value: datetime) -> str:
    return timestamp_value.strftime("%Y-%m-%dT%H:%M:%SZ")
