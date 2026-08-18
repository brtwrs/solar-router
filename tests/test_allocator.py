"""Tests for the allocation logic.

Run with:  python -m pytest tests/ -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "solar_router"))

from allocator import Consumer, allocate, budget_from, unused  # noqa: E402


def by_key(decisions):
    return {d.key: d for d in decisions}


def dial(key, priority=10, pmin=0, pmax=3000, **kw):
    """A consumer with only a number entity."""
    return Consumer(key, priority, pmin, pmax, has_number=True, **kw)


def relay(key, priority=10, rated=2300, **kw):
    """A consumer with only a switch."""
    return Consumer(key, priority, 0, rated, has_switch=True, **kw)


def both(key, priority=10, pmin=0, pmax=3000, **kw):
    """A consumer with a switch and a dial."""
    return Consumer(key, priority, pmin, pmax, has_number=True, has_switch=True, **kw)


# --------------------------------------------------------------- budget

def test_budget_adds_back_own_draw():
    """The whole point: our own consumption must not look like a shortage."""
    assert budget_from(grid_export=200, already_allocated=1000, reserve=0) == 1200


def test_budget_honours_reserve():
    assert budget_from(grid_export=1000, already_allocated=0, reserve=300) == 700


def test_budget_can_go_negative_when_importing():
    assert budget_from(grid_export=-500, already_allocated=0, reserve=0) == -500


# --------------------------------------------------------------- dial only

def test_dial_takes_what_fits():
    d = by_key(allocate(1500, [dial("boiler", pmin=200)]))["boiler"]
    assert d.allocated == 1500
    assert d.number_value == 1500


def test_dial_capped_at_max():
    assert by_key(allocate(5000, [dial("boiler")]))["boiler"].allocated == 3000


def test_dial_off_below_its_minimum():
    """Zero is off; that is why a dial needs no switch."""
    # allocated is what the device is actually set to right now.
    d = by_key(allocate(150, [dial("boiler", pmin=200, allocated=1500)]))["boiler"]
    assert d.allocated == 0
    assert d.number_value == 0  # actively dialled down
    assert d.reason == "below minimum"


def test_dial_already_at_zero_is_left_alone():
    d = by_key(allocate(150, [dial("boiler", pmin=200, allocated=0)]))["boiler"]
    assert d.allocated == 0
    assert d.number_value is None  # nothing to do


def test_dial_not_written_when_unchanged():
    d = by_key(allocate(1500, [dial("boiler", allocated=1500)]))["boiler"]
    assert d.allocated == 1500
    assert d.number_value is None  # no pointless service call


def test_priority_order_is_respected():
    got = by_key(allocate(4000, [dial("miner", priority=20), dial("boiler", priority=10)]))
    assert got["boiler"].allocated == 3000
    assert got["miner"].allocated == 1000


# --------------------------------------------------------------- switch only

def test_relay_turns_on_when_it_fits():
    d = by_key(allocate(2500, [relay("car")]))["car"]
    assert d.switch_on is True
    assert d.allocated == 2300


def test_relay_stays_off_when_it_does_not_fit():
    d = by_key(allocate(1000, [relay("car")]))["car"]
    assert d.switch_on is None
    assert d.allocated == 0


def test_running_relay_stays_on_while_budget_holds():
    d = by_key(allocate(2300, [relay("car", currently_on=True)]))["car"]
    assert d.switch_on is None
    assert d.allocated == 2300


def test_running_relay_goes_off_on_shortfall():
    d = by_key(allocate(-400, [relay("car", currently_on=True)]))["car"]
    assert d.switch_on is False


def test_minimum_on_time_keeps_it_running():
    d = by_key(allocate(-400, [relay("car", currently_on=True, held=True)]))["car"]
    assert d.switch_on is None
    assert d.reason == "held on"


def test_minimum_off_time_prevents_restart():
    d = by_key(allocate(5000, [relay("car", held=True)]))["car"]
    assert d.switch_on is None
    assert d.reason == "held off"


# --------------------------------------------------------------- switch + dial

def test_both_switches_on_and_dials_up():
    d = by_key(allocate(2000, [both("charger", pmin=1400, pmax=7400)]))["charger"]
    assert d.switch_on is True
    assert d.number_value == 2000
    assert d.allocated == 2000


def test_both_switches_off_below_minimum():
    d = by_key(allocate(600, [both("charger", pmin=1400, pmax=7400, currently_on=True)]))["charger"]
    assert d.switch_on is False
    assert d.allocated == 0


def test_both_leaves_switch_alone_when_already_correct():
    d = by_key(allocate(2000, [both("charger", pmin=1400, currently_on=True)]))["charger"]
    assert d.switch_on is None  # already on
    assert d.number_value == 2000


def test_both_respects_minimum_off_time():
    """Cannot start yet, so it must not claim the power either."""
    c = both("charger", pmin=1400, pmax=7400, held=True)
    d = by_key(allocate(3000, [c]))["charger"]
    assert d.switch_on is None
    assert d.allocated == 0
    assert d.reason == "held off"


def test_held_charger_does_not_starve_the_next_one():
    charger = both("charger", priority=10, pmin=1400, pmax=7400, held=True)
    boiler = dial("boiler", priority=20, pmax=3000)
    got = by_key(allocate(3000, [charger, boiler]))
    assert got["charger"].allocated == 0
    assert got["boiler"].allocated == 3000  # power was handed on


# --------------------------------------------------------------- misc

def test_unmanaged_is_skipped_and_keeps_its_budget():
    got = by_key(allocate(2000, [dial("miner", priority=10, managed=False), dial("boiler", priority=20)]))
    assert got["miner"].allocated == 0
    assert got["boiler"].allocated == 2000


def test_unused_is_what_nobody_took():
    decisions = allocate(2500, [dial("boiler", pmax=1000)])
    assert unused(2500, decisions) == 1500


def test_no_consumers_leaves_everything_unused():
    assert unused(1000, allocate(1000, [])) == 1000


def test_mixed_fleet_realistic():
    """Boiler on a dial, car on a relay, miner on a dial. 4 kW surplus."""
    got = by_key(
        allocate(
            4000,
            [
                dial("boiler", priority=10, pmin=200, pmax=3000),
                relay("car", priority=20, rated=2300),
                dial("miner", priority=30, pmin=500, pmax=5000),
            ],
        )
    )
    assert got["boiler"].allocated == 3000
    assert got["car"].allocated == 0  # 1000 left, needs 2300
    assert got["miner"].allocated == 1000
