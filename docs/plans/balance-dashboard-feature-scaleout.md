# Plan: Balance Dashboard Feature Scale-Out

## Objective

Add three additional analyst-facing features to the regional balance dashboard,
scale them across the Diesel and Jet static workbooks, deploy by regenerating
the self-contained workbook outputs, and verify the deployed artifacts.

## Three Additional Features

1. **Market Monitor**
   - Add a compact monitor strip above the balance sheet.
   - Surface the selected region's latest balance, prior-period change, the
     largest regional draw, and the lowest regional stock cover for the active
     frequency.
   - Keep it product-agnostic so Diesel and Jet use the same calculation path.

2. **Balance Heatmap Mode**
   - Add a display option that toggles intensity shading inside balance-table
     numeric cells.
   - Scale each row independently so large builds, draws, and stock moves are
     easy to scan without distorting the actual values.
   - Persist the option in the current view state and keep mobile layout stable.

3. **Saved View Presets**
   - Replace the write-only saved forecast button with a usable saved-view
     workflow.
   - Let users save, load, delete, and reset product-specific dashboard views
     using local browser storage.
   - Preserve frequency, year, chart region, chart focus, active sheet, legend,
     forecast, region-title, and heatmap settings.

## Scale And Deploy Approach

- Implement only in `src/build_balance_dashboards.ts`, the source of truth.
- Keep all features generic over `DashboardBundle.product`, `regionalBalance`,
  and existing metric definitions.
- Regenerate both static deployments with `npm run build:balances`:
  - `Diesel_Balance/index.html`
  - `Jet_Balance/index.html`
- Keep both generated HTML files self-contained, with no external script or
  stylesheet dependencies.

## Verification Gates

- `npm run typecheck` passes.
- `npm run build:balances` passes.
- Generated Diesel and Jet inline scripts parse.
- Generated Diesel and Jet HTML remain self-contained.
- Rendered QA proves:
  - Diesel balance sheet loads with 9 PADD group headers.
  - Market Monitor renders four monitor cards and updates when region changes.
  - Heatmap toggle applies and removes balance-table heat cells.
  - Saved View presets can save, load, delete, and reset a view.
  - Existing balance collapse/expand, chart zoom, chart summaries, tooltip,
    Sources sheet, and mobile no-overflow checks still pass.
  - Jet workbook loads with the same three features and no runtime errors.

## Execution Log

- Plan created for Market Monitor, Balance Heatmap Mode, and Saved View Presets.
- Implemented all three features in `src/build_balance_dashboards.ts`.
- Scaled the implementation through the shared generator so both Diesel and Jet
  workbooks receive the same feature set.
- Deployed by regenerating `Diesel_Balance/index.html` and
  `Jet_Balance/index.html` with `npm run build:balances`.
- Verified TypeScript, generated inline script syntax, self-contained HTML, and
  rendered Diesel/Jet behavior with Playwright.
- Rendered QA passed for Market Monitor updates, heatmap toggle and URL state,
  Saved View save/load/delete/reset, chart zoom and tooltip behavior, Source Hub
  rendering, mobile overflow checks, and Jet feature parity.
