# House Status module boundaries

The House Status panel is split into three functional ownership domains behind one stable navigation shell.

- **Energy** owns `domestic` and `flow`. They intentionally remain together because they share tariff, time-range, Power Down, import/export, battery and future EV data.
- **House** owns `home` and its floorplan/status surfaces.
- **Doorbell** owns `doorbell`, camera/event rendering and future doorbell actions.

## Safety rule

A change scoped to House or Doorbell must not modify Energy rendering/data code unless the PR explicitly declares a cross-module change. Likewise Energy changes must not alter camera/floorplan implementation.

The shell owns only navigation, selected mode, date/range controls and shared visual tokens.

## Migration

The first migration commit establishes executable ownership markers without changing the accepted UI. Subsequent PRs extract each owner into its own asset one at a time, with live acceptance after each extraction. Energy is the reference implementation and is extracted last so currently accepted energy/Power Down behaviour is not put at risk by the architectural change.


## Versioning contract

The visible runtime version is module-scoped, not shell-scoped. Domestic Energy and Full Energy Flow share the Energy module/version; Home Status has the House module/version; Doorbell has the Doorbell module/version. A change confined to one module increments only that module's visible version. The shell/custom-element generation may change for cache invalidation without implying that unchanged modules were revised.
