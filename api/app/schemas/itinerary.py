"""Response value objects for direct and one-transfer journeys."""

from __future__ import annotations

from dataclasses import dataclass, field

from api.app.schemas.snapshot import Pattern, PatternId, StopId, Weekday


@dataclass(frozen=True, slots=True)
class Leg:
    """A directional ride on one canonical pattern.

    Stop identifiers and indexes are deliberately kept as compact integers;
    API presentation can resolve stop names from the Stage 1 snapshot.
    """

    pattern_id: PatternId | None
    route_id: str
    direction_id: str | None
    service_ids: frozenset[str]
    operating_days: frozenset[Weekday]
    board_stop: StopId
    alight_stop: StopId
    board_index: int
    alight_index: int
    route_code: str | None = None
    headsigns: frozenset[str] = field(default_factory=frozenset)
    board_stop_name: str | None = None
    alight_stop_name: str | None = None
    mode: str = "Otobüs"
    walking_metres: int | None = None

    def __post_init__(self) -> None:
        if self.walking_metres is None and self.board_index >= self.alight_index:
            raise ValueError("A leg must satisfy board_index < alight_index")

    @property
    def is_walking(self) -> bool:
        return self.walking_metres is not None


@dataclass(frozen=True, slots=True)
class Itinerary:
    """A direct, one-transfer, or two-transfer itinerary."""

    legs: tuple[Leg, ...]
    # The days on which every leg in this itinerary operates.
    operating_days: frozenset[Weekday] = field(init=False)

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("An itinerary requires at least one leg")
        if self.transit_leg_count > 4 or len(self.legs) > 9:
            raise ValueError("A journey supports four rides, three transfers and endpoint walks")
        if any(
            first.alight_stop != second.board_stop
            for first, second in zip(self.legs, self.legs[1:])
        ):
            raise ValueError("Adjacent legs must meet at the same transfer stop")

        common_days = self.legs[0].operating_days
        for leg in self.legs[1:]:
            common_days = common_days.intersection(leg.operating_days)
        if not common_days:
            raise ValueError("No common operating day exists for all itinerary legs")
        object.__setattr__(self, "operating_days", frozenset(common_days))

    @property
    def transfer_stop(self) -> StopId | None:
        """The transfer stop for a two-leg itinerary, otherwise ``None``."""

        return self.legs[0].alight_stop if len(self.legs) == 2 else None

    @property
    def transit_leg_count(self) -> int:
        return sum(not leg.is_walking for leg in self.legs)


def leg_from_pattern(
    pattern: Pattern,
    *,
    board_stop: StopId,
    alight_stop: StopId,
    board_index: int,
    alight_index: int,
) -> Leg:
    """Create a response leg while enforcing the directional invariant."""

    return Leg(
        pattern_id=pattern.id,
        route_id=pattern.route_id,
        direction_id=pattern.direction_id,
        service_ids=pattern.service_ids,
        operating_days=pattern.operating_days,
        board_stop=board_stop,
        alight_stop=alight_stop,
        board_index=board_index,
        alight_index=alight_index,
        route_code=pattern.route_code,
        headsigns=pattern.headsigns,
        mode=pattern.mode,
    )


def walking_leg(
    *, board_stop: StopId, alight_stop: StopId, metres: int
) -> Leg:
    """Create a displayable foot connection between two nearby platforms."""

    return Leg(
        pattern_id=None,
        route_id="walk",
        direction_id=None,
        service_ids=frozenset(),
        operating_days=frozenset(Weekday),
        board_stop=board_stop,
        alight_stop=alight_stop,
        board_index=0,
        alight_index=0,
        route_code="Yürüme",
        mode="Yürüme",
        walking_metres=metres,
    )
