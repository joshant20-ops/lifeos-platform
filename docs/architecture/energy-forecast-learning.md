# LifeOS Forecast Learning Architecture

Updated: 2026-08-28T00:50:33+01:00

## Classification

### lifeos-energy-forecast

**KEEP / SIMPLIFY**

This service records timestamped Predbat forecast series, measured
actuals, and locked 30-minute forecast errors in
`forecast_history.sqlite`.

Predbat remains the forecast provider. LifeOS retains the historical
forecast-accuracy dataset and evaluation layer.

### lifeos-energy-shadow-learning

**KEEP / SIMPLIFY**

This service performs shadow-only walk-forward learning from the
collector's `forecast_errors` data.

It does not control Predbat, the battery, or the LifeOS planner.

## Scheduling

The duplicate shadow-learning timer has been retired.

Authoritative chain:

```
lifeos-energy-forecast.timer
        |
        v
lifeos-energy-forecast.service
        |
        | OnSuccess
        v
lifeos-energy-shadow-learning.service
```

This guarantees learning runs only after a successful fresh
forecast/actual/error collection.

## Transport

Direct Home Assistant state publication remains temporarily preserved.

Next simplification:

```
forecast analytics
        |
        v
retained MQTT
        |
        v
Home Assistant MQTT Discovery
```

The transport migration must preserve the SQLite history and shadow
learning algorithms.
