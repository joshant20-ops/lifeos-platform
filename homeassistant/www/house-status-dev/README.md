# House Status development panel

This directory is the isolated development copy served at `/house-status-dev`.

- Edit and test development UI here.
- The dev deploy installs only this directory under Home Assistant's `www/house-status-dev` and manages only the `lifeos-house-status-dev` panel entry.
- The stable loader imports the current dev bundle with a unique URL; refresh the HA page after a deployment to reload custom elements. This does not restart Home Assistant.
- The production panel at `/house-status` is deployed only from `homeassistant/releases/house-status/live/` through the explicit live deployment workflow.
- To promote a tested change, update the versioned production release bundle in a reviewed change, then manually run the live deployment workflow.
