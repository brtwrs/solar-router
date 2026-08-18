"""The allocation logic, deliberately free of Home Assistant.

Keeping this pure means it can be reasoned about and tested on its own. The
coordinator does the talking to Home Assistant; this file only decides.
"""

from __future__ import annotations

from dataclasses import dataclass

CONTROL_NUMBER = "number"
CONTROL_SWITCH = "switch"


@dataclass
class Consumer:
    """One thing that can absorb surplus power."""

    key: str
    priority: int
    control: str
    power_min: float
    power_max: float
    managed: bool = True
    # runtime
    currently_on: bool = False
    allocated: float = 0.0
    held: bool = False  # inside its minimum on/off window


@dataclass
class Decision:
    """What should happen to one consumer this cycle."""

    key: str
    allocated: float
    action: str  # "set", "on", "off", "none"
    reason: str


def budget_from(grid_export: float, already_allocated: float, reserve: float) -> float:
    """Power we may spend.

    grid_export is positive when exporting. We add back what our own consumers
    are drawing, because that draw is why the export is not higher. Forgetting
    this is what makes naive versions oscillate.
    """
    return grid_export + already_allocated - reserve


def allocate(budget: float, consumers: list[Consumer]) -> list[Decision]:
    """Hand the budget out in priority order (lower number first)."""
    decisions: list[Decision] = []
    remaining = budget

    for c in sorted(consumers, key=lambda x: x.priority):
        if not c.managed:
            decisions.append(Decision(c.key, 0.0, "none", "not managed"))
            continue

        if c.control == CONTROL_NUMBER:
            give = max(0.0, min(c.power_max, remaining))
            if give < c.power_min:
                give = 0.0
            action = "set" if abs(give - c.allocated) >= 1 else "none"
            reason = "modulating" if give else "below minimum"
            decisions.append(Decision(c.key, give, action, reason))
            remaining -= give
            continue

        # on/off
        rated = c.power_max or c.power_min
        if c.currently_on:
            if remaining >= 0 or c.held:
                reason = "on" if remaining >= 0 else "held on"
                decisions.append(Decision(c.key, rated, "none", reason))
                remaining -= rated
            else:
                decisions.append(Decision(c.key, 0.0, "off", "shortfall"))
        elif remaining >= rated and not c.held:
            decisions.append(Decision(c.key, rated, "on", "surplus available"))
            remaining -= rated
        else:
            reason = "held off" if c.held else "waiting for surplus"
            decisions.append(Decision(c.key, 0.0, "none", reason))

    return decisions


def unused(budget: float, decisions: list[Decision]) -> float:
    """Surplus nobody claimed."""
    return max(0.0, budget - sum(d.allocated for d in decisions))
