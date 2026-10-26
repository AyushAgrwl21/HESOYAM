"""Duplicate handling for one fetched extract.

Identical copies of a natural key are collapsed and counted. Conflicting copies
are all retained and counted. Nothing conflicting is averaged or dropped.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

RecordT = TypeVar("RecordT")

DEDUPLICATION_POLICY = (
    "Identical rows that share a natural key are stored once. Each extra copy is "
    "counted as an identical duplicate. Rows that share a natural key but differ "
    "in any stored field are all retained and counted as a conflict. Conflicts are "
    "not averaged and are not discarded. Rerunning ingestion replaces this study "
    "cache instead of appending another copy of the extract."
)


@dataclass(frozen=True)
class DeduplicationResult[RecordT]:
    retained_records: list[RecordT]
    identical_copies_collapsed: int
    conflicting_key_groups: int
    conflicting_records_retained: int


def deduplicate_records(
    records: list[RecordT],
    natural_key_of: Callable[[RecordT], tuple[object, ...]],
    signature_of: Callable[[RecordT], tuple[object, ...]],
) -> DeduplicationResult[RecordT]:
    grouped_records: dict[tuple[object, ...], list[RecordT]] = defaultdict(list)
    for record in records:
        grouped_records[natural_key_of(record)].append(record)

    retained_records: list[RecordT] = []
    identical_copies_collapsed = 0
    conflicting_key_groups = 0
    conflicting_records_retained = 0
    for grouped in grouped_records.values():
        unique_variants: list[RecordT] = []
        seen_signatures: set[tuple[object, ...]] = set()
        for record in grouped:
            signature = signature_of(record)
            if signature in seen_signatures:
                identical_copies_collapsed += 1
                continue
            seen_signatures.add(signature)
            unique_variants.append(record)
        if len(unique_variants) > 1:
            conflicting_key_groups += 1
            conflicting_records_retained += len(unique_variants)
        retained_records.extend(unique_variants)
    return DeduplicationResult(
        retained_records=retained_records,
        identical_copies_collapsed=identical_copies_collapsed,
        conflicting_key_groups=conflicting_key_groups,
        conflicting_records_retained=conflicting_records_retained,
    )
