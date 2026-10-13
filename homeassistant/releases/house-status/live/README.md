# House Status live release bundle

This is the versioned production bundle installed at `/local/house-status/`.
It was frozen from the verified live dashboard at commit `41b65fc45218d3af942e8b5071e93a1c15887f51`.

Normal development belongs in `homeassistant/www/house-status-dev/`. The live deploy workflow is manual and installs only this release bundle. Promote a tested version here through a reviewed change, then manually run **House Status Live Deploy**.


## v29 energy-page promotion

The v29 House Status entry keeps the v28 Home Status and Doorbell renderers unchanged and promotes the accepted DEV Domestic Energy Consumption and Full Energy Flow views. It includes Europe/London rolling periods, API-backed energy history and Year-only Power Down marker/legend suppression. The reviewed Live workflow installs v29 as a separate cache-busted entry and verifies the browser-served JavaScript against this release bundle before acceptance. v28 remains frozen.
