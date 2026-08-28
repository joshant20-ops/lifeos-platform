# LifeOS Energy MQTT Transport

Updated: 2026-08-28T01:05:51+01:00

## Architecture

Predbat + Home Assistant measurement inputs
→ LifeOS forecast accuracy collector
→ forecast_history.sqlite
→ retained MQTT `lifeos/energy/forecast/state`

Collector success
→ shadow learner
→ shadow_learning_report.json
→ retained MQTT `lifeos/energy/shadow_learning/state`

Home Assistant presentation uses MQTT Discovery.

## Preserved

- Predbat forecast input
- actual HA measurement input
- SQLite forecast/history/error dataset
- 30-minute forecast-error calculation
- walk-forward learning
- bounded corrections
- MAE/RMSE evaluation
- shadow-only operation
- no Predbat writes
- no battery/planner control

## Retired

- direct generated-state Home Assistant REST POST
- duplicate shadow-learning timer

## Scheduler

```
lifeos-energy-forecast.timer
        ↓
lifeos-energy-forecast.service
        ↓ OnSuccess
lifeos-energy-shadow-learning.service
```
