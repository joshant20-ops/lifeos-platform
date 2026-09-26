# House Status dashboard

Repository-managed Home Assistant dashboard at `/house-status`.

## Locked views

1. **Domestic Energy Consumption** — domestic running cost excluding home-battery and EV charging.
2. **Full Energy Flow** — electrical import/export with battery context and charge-only EV semantics.
3. **Home Status** — read-only floorplan state with one bounded Leave House action once exact entities are proven.
4. **Doorbell** — live doorbell camera page, automatically presented on enrolled shared displays after proven motion/bell entities and a supported display-navigation integration are mapped.

## Provenance-first rollout

The repository intentionally ships a safe foundation before live entity discovery. Existing proven LifeOS energy entities are used immediately. Gas cost, EV energy, interval GBP totals, aperture overlays, light/TV overlays and the Leave House action are not guessed.

Live acceptance must discover exact HA entity IDs and prove:
- interval energy × interval tariff cost attribution;
- house-use exclusion of battery/EV charging;
- gas energy and tariff source;
- EV charging telemetry;
- external window/door entities only;
- exact lights/TVs eligible for Leave House.

Unavailable entities must render neutral/grey rather than a false state.

## Floorplan replacement

`homeassistant/www/house-status/placeholder-floorplan.svg` is a disposable simulated asset. Replace the base drawing when the real ground/first-floor plans are supplied; keep state/entity overlay mapping separate from the artwork.

## Deployment

Deployment is privileged only through the fixed gateway operation:

```
sudo -n /usr/local/sbin/lifeos-deploy-gateway deploy-house-status-dashboard
```

The operation backs up existing HA storage/dashboard files, installs the floorplan asset, deploys the storage-mode dashboard, restarts Home Assistant, waits for health, and runs `verify-house-status-dashboard.py`.

The GitHub Actions runner must not receive general sudo or arbitrary script execution.

## Doorbell activation policy

The Doorbell page is status/view-only. Read-only discovery identifies the camera plus motion and bell-press trigger candidates before any automation is enabled.

- Motion requests the Doorbell view for 30 seconds.
- Further motion extends the active window instead of reopening it repeatedly.
- A bell press requests the Doorbell view for 90 seconds.
- Camera unavailable must be visibly neutral and explicit; stale imagery is not treated as live.
- Automatic navigation is limited to explicitly enrolled shared HA displays. Bedroom/private displays are not enrolled by default.
- The automation must not unlock/open a door, change camera configuration, or expose unrelated controls.
- No browser/display integration is invented. If Browser Mod, Fully Kiosk, WallPanel or another supported navigation target is not actually present, discovery records that as a live blocker while the Doorbell tab remains usable manually.
