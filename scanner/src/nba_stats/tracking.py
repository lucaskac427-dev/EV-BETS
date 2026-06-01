"""Spatial tracking data model — adapted from linouk23/NBA-Player-Movements.

Their object model (Game -> Event -> Moment -> Player/Ball, each with x/y/z) is
the right shape for ANY positional NBA data. We populate it from our pbp_events
shot coordinates today; it's ready for full SportVU / Second-Spectrum frame
tracking (every-25th-of-a-second player + ball positions) the moment we add a
source. From it we derive the spatial features projections love: shot zones,
distance distributions, where a player gets his looks vs a given defense.

NBA legacy coordinates: x in [-250, 250] tenths-of-a-foot (left/right of basket),
y in [0, ~470] tenths-of-a-foot from the baseline; basket at (0, 0).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot


@dataclass(frozen=True, slots=True)
class Position:
    """Court position in feet. Basket at origin; +x right, +y up the floor."""

    x: float
    y: float
    z: float = 0.0  # height, ball only

    @classmethod
    def from_legacy(cls, x_legacy: int | None, y_legacy: int | None) -> "Position | None":
        if x_legacy is None or y_legacy is None:
            return None
        return cls(x=x_legacy / 10.0, y=y_legacy / 10.0)

    @property
    def distance_ft(self) -> float:
        return hypot(self.x, self.y)


def shot_zone(pos: Position, made: bool | None = None) -> str:
    """Coarse shot zone — the kind of feature a projection model wants."""
    d = pos.distance_ft
    if d <= 4:
        return "rim"
    if d <= 14:
        return "short_mid"
    if d < 22:
        return "long_mid"
    if abs(pos.x) >= 220 and pos.y <= 92:
        return "corner_three"
    return "above_break_three"


@dataclass(slots=True)
class PlayerSnapshot:
    person_id: int
    name: str
    team_tricode: str
    pos: Position


@dataclass(slots=True)
class Moment:
    """One frame of full tracking (populated only when frame data exists)."""

    period: int
    clock: str
    ball: Position | None
    players: list[PlayerSnapshot] = field(default_factory=list)


@dataclass(slots=True)
class TrackedEvent:
    game_id: str
    action_number: int
    period: int
    clock: str
    action_type: str | None
    player_name: str | None
    description: str | None
    shot: Position | None
    shot_made: bool | None
    score_home: int | None
    score_away: int | None
    moments: list[Moment] = field(default_factory=list)

    @property
    def zone(self) -> str | None:
        return shot_zone(self.shot, self.shot_made) if self.shot else None


@dataclass(slots=True)
class GameTracking:
    game_id: str
    events: list[TrackedEvent]

    def shots(self) -> list[TrackedEvent]:
        return [e for e in self.events if e.shot is not None]

    def player_shot_chart(self, player: str) -> dict[str, dict[str, int]]:
        """{zone: {made, attempts}} for one player — instant projection feature."""
        chart: dict[str, dict[str, int]] = {}
        for e in self.shots():
            if e.player_name != player:
                continue
            z = e.zone or "unknown"
            cell = chart.setdefault(z, {"made": 0, "attempts": 0})
            cell["attempts"] += 1
            if e.shot_made:
                cell["made"] += 1
        return chart


async def load_game_tracking(pool, game_id: str) -> GameTracking:
    """Build the tracking object model from pbp_events for one game."""
    rows = await pool.fetch(
        """SELECT action_number, period, clock, action_type, player_name,
                  description, x_legacy, y_legacy, shot_result, score_home, score_away
           FROM pbp_events WHERE game_id=$1 ORDER BY action_number""",
        game_id,
    )
    events: list[TrackedEvent] = []
    for r in rows:
        is_shot = (r["shot_result"] or "") in ("Made", "Missed")
        events.append(
            TrackedEvent(
                game_id=game_id,
                action_number=r["action_number"],
                period=r["period"],
                clock=r["clock"],
                action_type=r["action_type"],
                player_name=r["player_name"],
                description=r["description"],
                shot=Position.from_legacy(r["x_legacy"], r["y_legacy"]) if is_shot else None,
                shot_made=(r["shot_result"] == "Made") if is_shot else None,
                score_home=r["score_home"],
                score_away=r["score_away"],
            )
        )
    return GameTracking(game_id=game_id, events=events)
