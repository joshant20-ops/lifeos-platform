# House Status visual acceptance references

Issue: #1141

These references are the authoritative visual target for the first three House Status tabs. They supersede the improvised Lovelace layouts produced during early implementation.

## Reference assets

The original approved raster mockups are preserved in the project conversation as:
- `19589.png` — combined Domestic Energy Consumption (left) and Full Energy Flow (right).
- `19588.png` — Home Status floorplan view.

Binary upload is not supported by the current GitHub connector, so this repository record captures the immutable visual contract until the original PNG bytes can be committed through the governed runner. Do not substitute stock/reference web imagery.

## 1. Domestic Energy Consumption

Match `19589.png`, left half.

Required visual hierarchy:
- House Status title/header.
- Top tab selector.
- Date field with previous/next controls.
- Period controls: Today / Day / Month / Year / Date range.
- One dominant, nearly full-width chart.
- Chart is split visually into Today and Tomorrow; unpublished tomorrow tariff remains blank and says prices are not yet available.
- Lines: electricity price, domestic electricity cost excluding battery/car charging, export earnings, gas cost.
- Summary row below chart: Electricity used; Export earnings; Gas used; Total energy cost.
- Currency is human precision (2 decimals), energy/rates concise.
- No explanatory implementation-status cards.

## 2. Full Energy Flow

Match `19589.png`, right half.

Required visual hierarchy:
- Same header/date/period-control geometry as Domestic Energy.
- One dominant full-width chart.
- Positive stacked bars: house usage, battery charging, EV/car charging.
- Negative export bars: PV/grid export and battery export only where deterministic attribution exists.
- Overlay lines: electricity price and battery SOC.
- Tomorrow blank/null if unpublished.
- Summary row: House usage; Battery; Car (EV); Export earnings; Gas used.
- Bottom total-energy-cost strip.
- Tesla remains charge-only; no V2G/V2H.
- If EV not installed, preserve the card geometry but show Not installed / £0 / 0 kWh rather than invent telemetry.

## 3. Home Status

Match `19588.png`.

Required visual hierarchy:
- House Status title/header and tab selector.
- House secure status and prominent Leave House control at upper right.
- Large Ground Floor panel.
- Large First Floor panel.
- Bottom legend.
- Floorplan is the dominant content; avoid generic HA tiles competing for space.
- External windows/doors: translucent green=open, red=closed.
- TV: green=on, red=off.
- Lights: red=on, green=off.
- unavailable: grey + !.
- No occupancy/person tracking.
- No internal-door state.
- Until real floorplans and aperture/light sensors are installed, preserve the target geometry with clearly planned/not-installed state; never claim House secure.

## Acceptance rule

A deployment PASS is not visual acceptance. These tabs are complete only when an actual rendered screenshot at the intended display size is compared against these references for:
- overall geometry,
- information hierarchy,
- chart/card proportions,
- typography/precision,
- responsive use of available width,
- absence of placeholder/explanatory implementation text,
- data semantics.

Structural HA validation remains necessary but is insufficient.
