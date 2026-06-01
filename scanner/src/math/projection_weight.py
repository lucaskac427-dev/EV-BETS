"""Linear ramp of projection weight from 0.20 (day 0) to 0.40 (day 90)."""

PROJECTION_WEIGHT_START = 0.20
PROJECTION_WEIGHT_END = 0.40
PROJECTION_RAMP_DAYS = 90


def current_projection_weight(days_since_launch: int) -> float:
    """Linearly interpolated projection blend weight.

    Clamped at both ends (negative → start, >=90 → end).
    """
    if days_since_launch <= 0:
        return PROJECTION_WEIGHT_START
    if days_since_launch >= PROJECTION_RAMP_DAYS:
        return PROJECTION_WEIGHT_END
    pct = days_since_launch / PROJECTION_RAMP_DAYS
    return PROJECTION_WEIGHT_START + pct * (PROJECTION_WEIGHT_END - PROJECTION_WEIGHT_START)
