# House Status DEV energy history

## Data sources and path

- Enphase Envoy telemetry is collected by the existing LifeOS Energy service. Recent raw samples are retained for at least 842 hours (35 days) and compacted into tariff-aligned 30-minute SQLite rollups. The rollup table is local caching for reliable history; Home Assistant Recorder is not used as a second long-term energy store.
- Octopus import prices come from the configured account tariff's historical `standard-unit-rates`. Each available Enphase half-hour is joined to the matching tariff slot.
- `domestic_import_cost_gbp` is calculated per interval as `domestic_import_kwh × import_p_per_kwh ÷ 100`.
- The 30-minute rollup query is `/api/energy/rollups?start=<unix-seconds>&end=<unix-seconds>&granularity=30m`. The start is inclusive and end exclusive.

The API returns only intervals with Enphase history; it does not invent zero-use intervals. It includes UTC timestamps, Europe/London local boundaries, tariff price, calculated cost, `coverage_percent`, `complete`, and `missing_price_slots`. Local-day boundaries are converted to UTC before querying, so 23-hour and 25-hour days retain the correct half-hour counts at daylight-saving changes.

## DEV views

- Day: available half-hour intervals.
- Week: daily historical values.
- Month: weekly aggregation.
- Year: monthly aggregation.

The DEV chart labels the selected date or range. When history coverage is below 99%, it labels the result as partial and withholds the whole-period cost and average price. Missing intervals remain missing; they are not presented as zero consumption.

## Current historical coverage

Live acceptance on 13 October 2026 returned 3,702 of 13,726 half-hour intervals for 2026 YTD (27.0%), across five month buckets. This is retained Enphase history, not a complete calendar-year record. The Year view shows the recorded monthly values and labels them partial; its 152.926 kWh and £34.81 are partial-period totals. Future collection adds further intervals to the local rollup store.

For the regression week beginning 28 September 2026, the API returned all 336 intervals. Rollup usage and cost matched the independent Enphase interval report and Octopus tariff prices: 15.634 kWh, £3.86, and 92.4% mean Enphase sample coverage. Day, Week, and Month regression views also returned complete requested intervals during live acceptance.

## Deployment boundary and recovery

The governed deployment path verified the Energy API and Home Assistant health after deployment/restart, then deployed only `/local/house-status-dev/` and verified the `/house-status-dev` panel configuration and isolation. Production House Status release assets were not changed or promoted.

Evidence for the current DEV acceptance is recorded on issue/PR #1583 and Actions runs #38409683430 (Energy API deployment/recovery) and #38409683094 (DEV panel deployment and live verification).
