"""Tests for the allocation logic.

Run with:  python -m pytest tests/ -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "solar_router"))

from allocator import (  # noqa: E402
    CONTROL_NUMBER,
    CONTROL_SWITCH,
    Consumer,
    allocate,
    budget_from,
    unused,
)


def by_key(decisions):
    return {d.key: d for d in decisions}


# --------------------------------------------------------------- budget

def test_budget_adds_back_own_draw():
    """The whole point: our own consumption must not look like a shortage."""
    # Exporting 200 W while our boiler already eats 1000 W -> 1200 W available.
    assert budget_from(grid_export=200, already_allocated=1000, reserve=0) == 1200


def test_budget_honours_reserve():
    assert budget_from(grid_export=1000, already_allocated=0, reserve=300) == 700


def test_budget_can_go_negative_when_importing():
    assert budget_from(grid_export=-500, already_allocated=0, reserve=0) == -500


# --------------------------------------------------------------- modulating

def test_modulating_takes_what_fits():
    boiler = Consumer("boiler", 10, CONTROL_NUMBER, power_min=200, power_max=3000)
    d = by_key(allocate(1500, [boiler]))["boiler"]
    assert d.allocated == 1500
    assert d.action == "set"


def test_modulating_capped_at_max():
    boiler = Consumer("boiler", 10, CONTROL_NUMBER, power_min=200, power_max=3000)
    assert by_key(allocate(5000, [boiler]))["boiler"].allocated == 3000


def test_modulating_off_below_its_minimum():
    boiler = Consumer("boiler", 10, CONTROL_NUMBER, power_min=200, power_max=3000)
    d = by_key(allocate(150, [boiler]))["boiler"]
    assert d.allocated == 0
    assert d.reason == "below minimum"


def test_priority_order_is_respected():
    boiler = Consumer("boiler", 10, CONTROL_NUMBER, power_min=0, power_max=3000)
    miner = Consumer("miner", 20, CONTROL_NUMBER, power_min=0, power_max=3000)
    got = by_key(allocate(4000, [miner, boiler]))
    assert got["boiler"].allocated == 3000  # priority 10 first
    assert got["miner"].allocated == 1000  # gets the remainder


# --------------------------------------------------------------- on/off

def test_switch_turns_on_when_it_fits():
    car = Consumer("car", 10, CONTROL_SWITCH, power_min=0, power_max=2300)
    d = by_key(allocate(2500, [car]))["car"]
    assert d.action == "on"
    assert d.allocated == 2300


def test_switch_stays_off_when_it_does_not_fit():
    car = Consumer("car", 10, CONTROL_SWITCH, power_min=0, power_max=2300)
    d = by_key(allocate(1000, [car]))["car"]
    assert d.action == "none"
    assert d.allocated == 0


def test_running_switch_stays_on_while_budget_holds():
    car = Consumer("car", 10, CONTROL_SWITCH, power_min=0, power_max=2300, currently_on=True)
    # Budget already includes the car's own draw, so 2300 means "exactly enough".
    d = by_key(allocate(2300, [car]))["car"]
    assert d.action == "none"
    assert d.allocated == 2300


def test_running_switch_goes_off_on_shortfall():
    car = Consumer("car", 10, CONTROL_SWITCH, power_min=0, power_max=2300, currently_on=True)
    d = by_key(allocate(-400, [car]))["car"]
    assert d.action == "off"


def test_minimum_on_time_keeps_it_running():
    car = Consumer(
        "car", 10, CONTROL_SWITCH, power_min=0, power_max=2300, currently_on=True, held=True
    )
    d = by_key(allocate(-400, [car]))["car"]
    assert d.action == "none"
    assert d.reason == "held on"


def test_minimum_off_time_prevents_restart():
    car = Consumer("car", 10, CONTROL_SWITCH, power_min=0, power_max=2300, held=True)
    d = by_key(allocate(5000, [car]))["car"]
    assert d.action == "none"
    assert d.reason == "held off"


# --------------------------------------------------------------- misc

def test_unmanaged_is_skipped_and_keeps_its_budget():
    off = Consumer("miner", 10, CONTROL_NUMBER, power_min=0, power_max=3000, managed=False)
    boiler = Consumer("boiler", 20, CONTROL_NUMBER, power_min=0, power_max=3000)
    got = by_key(allocate(2000, [off, boiler]))
    assert got["miner"].allocated == 0
    assert got["boiler"].allocated == 2000  # not eaten by the unmanaged one


def test_unused_is_what_nobody_took():
    boiler = Consumer("boiler", 10, CONTROL_NUMBER, power_min=0, power_max=1000)
    decisions = allocate(2500, [boiler])
    assert unused(2500, decisions) == 1500


def test_no_consumers_leaves_everything_unused():
    assert unused(1000, allocate(1000, [])) == 1000


def test_mixed_fleet_realistic():
    """Boiler modulating, car on/off, miner last. 4 kW surplus."""
    boiler = Consumer("boiler", 10, CONTROL_NUMBER, power_min=200, power_max=3000)
    car = Consumer("car", 20, CONTROL_SWITCH, power_min=0, power_max=2300)
    miner = Consumer("miner", 30, CONTROL_NUMBER, power_min=500, power_max=5000)

    got = by_key(allocate(4000, [boiler, car, miner]))
    assert got["boiler"].allocated == 3000  # takes its fill first
    assert got["car"].allocated == 0  # 1000 left, needs 2300
    assert got["miner"].allocated == 1000  # modulates into the remainder
