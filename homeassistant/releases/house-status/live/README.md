# House Status live release bundle

This is the versioned production bundle installed at `/local/house-status/`.
It was frozen from the verified live dashboard at commit `41b65fc45218d3af942e8b5071e93a1c15887f51`.

Normal development belongs in `homeassistant/www/house-status-dev/`. The live deploy workflow is manual and installs only this release bundle. Promote a tested version here through a reviewed change, then manually run **House Status Live Deploy**.

The v29 energy bundle is retained as an inert candidate artifact. The production registration and Live deploy path remain on v28 until promotion is explicitly approved; the candidate file and its CI regression do not authorize Live promotion.
