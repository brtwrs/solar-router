# Solar Router

Spend your own solar power instead of exporting it.

You tell it which sensor reports your grid power, then add consumers — a boiler,
a car charger, a heat pump, a miner. Each gets a priority. Every cycle the
integration works out how much surplus there is and hands it out, top priority
first. Devices with an adjustable power setting are dialled to whatever fits;
on/off devices are switched when their full draw fits.

This is deliberately reactive, not predictive. It does not forecast the weather
or optimise against energy prices — it looks at what is happening right now and
divides it up. If you need forecasting, look at EMHASS instead.

## Install

Copy `custom_components/solar_router` into your Home Assistant `config`
directory and restart. Then **Settings → Devices & Services → Add integration →
Solar Router**.

## Setting it up

**The hub** asks for one thing that matters: the sensor reporting grid power.
Tell it whether export shows as a negative number (usually yes). Optionally keep
a reserve in watts as a buffer, and set how often to recalculate.

**Consumers** are added with the `+` on the integration page. Per consumer:

| Field | Meaning |
|---|---|
| How is it controlled | An adjustable `number` entity, or an on/off `switch` |
| Minimum power | Below this it is not worth running. On/off devices: leave at 0 |
| Maximum power | The ceiling. For on/off: what it draws when running |
| Priority | Lower number is served first |
| Minimum on/off time | Keeps relays from chattering |

Each consumer gets a device with two entities: the power currently routed to it,
and a **Managed** switch to take it out of the routing when you want to run it
by hand.

## How the surplus is worked out

The one thing worth understanding:

```
budget = current export + what our own consumers already draw − reserve
```

Adding back your own draw is essential. Without it, switching the boiler on
makes the export disappear, which looks like a shortage, which switches the
boiler off again — and round it goes. With it, the budget stays stable and each
consumer simply holds its share.

## Tests

The allocation logic lives in `allocator.py` and has no Home Assistant imports,
so it can be tested on its own:

```bash
python -m pytest tests/ -q
```

## Status

Version 0.1.0. Written against Home Assistant 2026.8. Uses config subentries,
which need a reasonably recent Home Assistant.
