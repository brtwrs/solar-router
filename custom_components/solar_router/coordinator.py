"""Talks to Home Assistant; the deciding happens in allocator.py."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .allocator import (
    Consumer,
    Phase,
    allocate,
    budget_from,
    should_settle,
    unused,
)
from .const import (
    CONF_GRID_EXPORT_IS_NEGATIVE,
    CONF_GRID_SENSOR,
    CONF_INTERVAL,
    CONF_MIN_OFF,
    CONF_MIN_ON,
    CONF_NAME,
    CONF_NUMBER_ENTITY,
    CONF_PHASE,
    CONF_POWER_MAX,
    CONF_POWER_MIN,
    CONF_POWER_SENSOR,
    CONF_PRIORITY,
    CONF_RESERVE,
    CONF_SETTLE,
    CONF_SWITCH_ENTITY,
    DEFAULT_EXPORT_IS_NEGATIVE,
    DEFAULT_INTERVAL,
    DEFAULT_MIN_OFF,
    DEFAULT_MIN_ON,
    DEFAULT_PHASE_LIMIT,
    DEFAULT_PRIORITY,
    DEFAULT_RESERVE,
    DEFAULT_SETTLE,
    DOMAIN,
    EVENT_PHASE_LIMIT,
    PHASES,
    SUBENTRY_TYPE_CONSUMER,
    conf_phase_limit,
    conf_phase_sensor,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class ConsumerState:
    """Runtime state we keep between cycles."""

    subentry_id: str
    name: str
    allocated: float = 0.0
    claim: float = 0.0
    managed: bool = True
    forced: bool = False
    last_change: datetime | None = None
    reason: str = "idle"


@dataclass
class RouterData:
    """Snapshot handed to the entities."""

    surplus: float = 0.0
    budget: float = 0.0
    unused: float = 0.0
    settling: bool = False
    consumers: dict[str, ConsumerState] = field(default_factory=dict)


class SolarRouterCoordinator(DataUpdateCoordinator[RouterData]):
    """Reads the grid sensor, asks the allocator, applies the outcome."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Set the polling interval from the entry and start empty."""
        self.entry = entry
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                seconds=int(
                    entry.options.get(
                        CONF_INTERVAL, entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
                    )
                )
            ),
        )
        self._states: dict[str, ConsumerState] = {}
        self._last_action: float | None = None
        self._grid_missing_logged = False

    # ------------------------------------------------------------------ reading

    def _option(self, key: str, default: Any) -> Any:
        """Options win over data, so reconfiguring takes effect."""
        return self.entry.options.get(key, self.entry.data.get(key, default))

    def _numeric(self, entity_id: str | None) -> float | None:
        """Read an entity as a number, normalising kW to W."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        unit = (state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) or "").lower()
        if unit in ("kw", "kilowatt"):
            value *= 1000
        return value

    def _read_grid(self) -> float | None:
        """Grid power in watts, positive meaning export."""
        value = self._numeric(self._option(CONF_GRID_SENSOR, None))
        if value is None:
            return None
        if self._option(CONF_GRID_EXPORT_IS_NEGATIVE, DEFAULT_EXPORT_IS_NEGATIVE):
            value = -value
        return value

    def _meld_fasegrens(self, cfg: dict[str, Any], key: str) -> None:
        """Tell the rest of Home Assistant that a phase limit cut something off."""
        fase = cfg.get(CONF_PHASE)
        stroom = self._numeric(self._option(conf_phase_sensor(fase), None))
        self.hass.bus.async_fire(
            EVENT_PHASE_LIMIT,
            {
                "consumer": cfg.get(CONF_NAME, key),
                "phase": fase,
                "current": stroom,
                "limit": float(
                    self._option(conf_phase_limit(fase), DEFAULT_PHASE_LIMIT)
                ),
            },
        )

    def _read_phases(self) -> dict[str, Phase]:
        """Phases that have a readable current sensor, with their limit.

        A phase whose sensor is missing or unreadable is left out, so nothing
        on it is limited. Better that than switching everything off on a
        sensor that has gone unavailable.
        """
        fasen: dict[str, Phase] = {}
        for fase in PHASES:
            stroom = self._numeric(self._option(conf_phase_sensor(fase), None))
            if stroom is None:
                continue
            grens = float(
                self._option(conf_phase_limit(fase), DEFAULT_PHASE_LIMIT)
            )
            fasen[fase] = Phase(current=abs(stroom), limit=grens)
        return fasen

    def _subentries(self) -> list[ConfigSubentry]:
        """Return the consumer subentries, ignoring any other type."""
        return [
            s
            for s in self.entry.subentries.values()
            if s.subentry_type == SUBENTRY_TYPE_CONSUMER
        ]

    def state_for(self, subentry_id: str, name: str = "") -> ConsumerState:
        """Bookkeeping for one consumer, created on first use."""
        if subentry_id not in self._states:
            self._states[subentry_id] = ConsumerState(subentry_id, name)
        return self._states[subentry_id]

    def _held(self, state: ConsumerState, seconds: int) -> bool:
        """Still inside the minimum on/off window."""
        if state.last_change is None or seconds <= 0:
            return False
        return (dt_util.utcnow() - state.last_change).total_seconds() < seconds

    def _switch_is_on(self, entity_id: str | None) -> bool:
        """Whether a consumer's switch is currently on."""
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        return state is not None and state.state == STATE_ON

    def input_snapshot(self) -> dict[str, Any]:
        """Collect what every source entity reads right now, for diagnostics."""
        grid_sensor = self._option(CONF_GRID_SENSOR, None)
        snapshot: dict[str, Any] = {
            "grid_sensor": grid_sensor,
            "grid_raw": self._numeric(grid_sensor),
            "grid_normalised": self._read_grid(),
            "consumers": {},
        }
        for subentry in self._subentries():
            cfg = subentry.data
            snapshot["consumers"][subentry.title] = {
                CONF_NUMBER_ENTITY: self._numeric(cfg.get(CONF_NUMBER_ENTITY)),
                CONF_POWER_SENSOR: self._numeric(cfg.get(CONF_POWER_SENSOR)),
                CONF_SWITCH_ENTITY: self._switch_is_on(cfg.get(CONF_SWITCH_ENTITY)),
            }
        return snapshot

    # ------------------------------------------------------------------ applying

    async def _set_number(self, entity_id: str, value: float) -> None:
        """Dial a modulating consumer to a new setpoint."""
        await self.hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entity_id, "value": round(value)},
            blocking=False,
        )

    async def _set_switch(self, entity_id: str, on: bool) -> None:
        """Flip an on/off consumer."""
        await self.hass.services.async_call(
            "switch",
            "turn_on" if on else "turn_off",
            {"entity_id": entity_id},
            blocking=False,
        )

    # ------------------------------------------------------------------ one cycle

    async def _async_update_data(self) -> RouterData:
        """Run one cycle: read, decide, apply."""
        grid_sensor = self._option(CONF_GRID_SENSOR, None)
        grid = self._read_grid()
        if grid is None:
            # No usable reading. Change nothing rather than guess, and let the
            # entities go unavailable so it is visible that we are not steering.
            if not self._grid_missing_logged:
                self._grid_missing_logged = True
                _LOGGER.warning(
                    "Grid sensor %s is unavailable or not numeric; not routing until"
                    " it returns",
                    grid_sensor,
                )
            raise UpdateFailed(f"No usable reading from {grid_sensor}")

        if self._grid_missing_logged:
            self._grid_missing_logged = False
            _LOGGER.info("Grid sensor %s is readable again", grid_sensor)

        # After acting, the meter still describes the world as it was. Deciding
        # again on that reading is how a controller overshoots, so hold until a
        # genuinely newer measurement arrives.
        grid_state = self.hass.states.get(grid_sensor)
        grid_ts = grid_state.last_updated.timestamp() if grid_state else None
        if should_settle(
            grid_ts,
            self._last_action,
            dt_util.utcnow().timestamp(),
            float(self._option(CONF_SETTLE, DEFAULT_SETTLE)),
        ):
            return RouterData(surplus=grid, settling=True, consumers=dict(self._states))

        subs = {s.subentry_id: s for s in self._subentries()}

        consumers: list[Consumer] = []
        for sid, sub in subs.items():
            cfg = sub.data
            st = self.state_for(sid, cfg.get("name", sub.title))
            st.name = cfg.get("name", sub.title)

            number_entity = cfg.get(CONF_NUMBER_ENTITY)
            switch_entity = cfg.get(CONF_SWITCH_ENTITY)
            on_now = self._switch_is_on(switch_entity)

            # Compare against what the device is really set to, not against our
            # own bookkeeping. After a restart those disagree, and trusting the
            # bookkeeping would leave a device running that should be off.
            actual = self._numeric(number_entity)
            if actual is None:
                actual = st.allocated

            hold = int(
                cfg.get(CONF_MIN_ON, DEFAULT_MIN_ON)
                if on_now
                else cfg.get(CONF_MIN_OFF, DEFAULT_MIN_OFF)
            )

            consumers.append(
                Consumer(
                    key=sid,
                    priority=int(cfg.get(CONF_PRIORITY, DEFAULT_PRIORITY)),
                    power_min=float(cfg.get(CONF_POWER_MIN, 0)),
                    power_max=float(cfg.get(CONF_POWER_MAX, 0)),
                    has_number=bool(number_entity),
                    has_switch=bool(switch_entity),
                    managed=st.managed,
                    forced=st.forced,
                    currently_on=on_now,
                    allocated=actual,
                    measured=self._numeric(cfg.get(CONF_POWER_SENSOR)),
                    held=self._held(st, hold),
                    phase=(
                        cfg.get(CONF_PHASE) if cfg.get(CONF_PHASE) in PHASES else None
                    ),
                )
            )

        # Use the measurements we just read, not last cycle's bookkeeping.
        # Taking the older figure makes the dead time a whole cycle longer than
        # it needs to be, which is what lets the ramp run away.
        already = sum(
            (c.measured if c.measured is not None else c.allocated)
            for c in consumers
            if c.managed
        )
        budget = budget_from(
            grid, already, float(self._option(CONF_RESERVE, DEFAULT_RESERVE))
        )

        decisions = allocate(budget, consumers, self._read_phases())

        data = RouterData(surplus=grid, budget=budget)
        for d in decisions:
            sub = subs.get(d.key)
            if sub is None:
                continue
            cfg = sub.data
            st = self.state_for(d.key)

            if d.number_value is not None and cfg.get(CONF_NUMBER_ENTITY):
                await self._set_number(cfg[CONF_NUMBER_ENTITY], d.number_value)
                st.last_change = dt_util.utcnow()
                self._last_action = st.last_change.timestamp()

            if d.reason == "phase limit" and (
                d.switch_on is False or d.number_value == 0
            ):
                # Only when we actually take something away: not every cycle
                # that a start is refused, or you would be flooded.
                self._meld_fasegrens(cfg, d.key)

            if d.switch_on is not None and cfg.get(CONF_SWITCH_ENTITY):
                await self._set_switch(cfg[CONF_SWITCH_ENTITY], d.switch_on)
                st.last_change = dt_util.utcnow()
                self._last_action = st.last_change.timestamp()

            st.allocated = d.allocated
            st.claim = d.claim
            st.reason = d.reason
            data.consumers[d.key] = st

        data.unused = unused(budget, decisions)
        return data
