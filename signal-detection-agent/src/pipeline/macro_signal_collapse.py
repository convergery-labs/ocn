"""COLLAPSE (spec section 6): merge survivors (rows where suppressed_by is
None) that trace to the same release inside the same knowledge_time window
into one event. Distinct from suppression - suppression removes duplicate
FACTS (the same number counted twice); collapse merges distinct-but-related
facts from one release into one narrative unit.

Decision made earlier in this project (confirmed with the user): collapse
is scoped to same-channel, same-release groups only. A same-release,
cross-channel pair does NOT collapse - INTERPRET's output schema has
exactly one `channel` per event, so a cross-channel merge doesn't fit it.
Each survivor that doesn't join a same-channel group becomes its own
single-member event.

Known tension, not hidden: the spec's own worked example (DFII5+DGS1 on
2026-08-28) describes those two surviving as ONE collapsed event - but
DFII5 is channel=discount_rate and DGS1 is channel=policy_path, different
channels. Under this module's same-channel-only rule, they will NOT
collapse and will surface as two separate events instead of one. This
module intentionally implements the documented decision, not the spec's
narrative outcome for that specific example - flagged for a final sanity
check once this is wired into a real pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pipeline.macro_signal_suppress import SuppressibleResult
from pipeline.macro_signal_thresholds import Channel, THRESHOLDS, EXCLUDED_FROM_TIERING


@dataclass
class CollapsedEvent:
    release_id: int
    knowledge_time: datetime
    channel: Channel
    members: list[SuppressibleResult] = field(default_factory=list)

    @property
    def member_ids(self) -> list[str]:
        return [m.series_id for m in self.members]


def _channel_of(series_id: str) -> Channel:
    if series_id in EXCLUDED_FROM_TIERING:
        raise ValueError(f"{series_id} is excluded from tiering, has no channel-bearing event.")
    return THRESHOLDS[series_id].channel


def collapse_events(
    survivors: list[SuppressibleResult],
    release_id_of: dict[str, int],
    knowledge_time_of: dict[str, datetime],
) -> list[CollapsedEvent]:
    """Groups survivors (suppressed_by is None) by (release_id, channel).
    release_id_of/knowledge_time_of map series_id -> its release_id /
    knowledge_time for this date's batch (caller's responsibility - this
    module has no knowledge of FRED release calendars itself).
    """
    groups: dict[tuple[int, Channel], CollapsedEvent] = {}
    for r in survivors:
        if r.suppressed_by is not None:
            continue
        release_id = release_id_of[r.series_id]
        channel = _channel_of(r.series_id)
        key = (release_id, channel)
        if key not in groups:
            groups[key] = CollapsedEvent(
                release_id=release_id,
                knowledge_time=knowledge_time_of[r.series_id],
                channel=channel,
            )
        groups[key].members.append(r)
    return list(groups.values())
