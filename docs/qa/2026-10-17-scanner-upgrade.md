# PaperBot Pro Scanner upgrade

Branch: `codex/scanner-dashboard-upgrade`

## Scope and safety

Inspected CLAUDE.md, README.md, both implementation plans, previous visual QA, frontend guidance, API contracts, scanner, market-data cache, and engine signal logging before implementation. No backend, strategy, risk, database, configuration, credentials or engine-process changes. Existing public GET endpoints supply all displayed data. Automatic paper entry remained disabled during review.

## Changes

- Geist typography (fixed self-referencing font token and explicitly applied the loaded font), dark terminal layout, summary metrics, aligned tabular financial values and restrained signal colours.
- All engine-selected assets remain visible, including ineligible instruments. Search by name/symbol, ten sortable columns, composable trend/candidate/eligibility/minimum-volume filters, reset and empty states.
- Sticky asset column inside a keyboard-focusable horizontal table region. Responsive filter wrapping and summary grid.
- Keyboard-accessible asset buttons open a Radix analysis drawer, with exact instrument exclusion reasons, engine metrics and historical decision reasons.
- Compact interactive TradingView candlestick chart in the drawer, five timeframes, volume and EMA overlays. Fetches only the selected verified instrument; no invented sparkline history or per-row exchange fan-out.
- Separate market-snapshot and scanner-cycle timestamps. Candle-cache age is explicitly labelled as age at evaluation, not current quote age. Historical accepted/rejected decisions are never presented as current approval.
- Scanner suppresses the existing API client's synthetic fallbacks. Missing API data, decision logs and candles render unavailable states. Other pages retain their existing behaviour.
- Membership history preserved.

## Verification

- Python: `.venv/bin/python -m pytest -q` — **114 passed**, one existing Starlette/httpx deprecation warning.
- Frontend: `npm run lint` — passed.
- Production: `npm run build -- --webpack` — passed, including TypeScript and all 12 generated pages. Default Turbopack build attempted but blocked by a worker-port permission error, including the escalated attempt. Webpack needed network permission for the project's existing Google Font downloads.
- Scanner: `npm run test:scanner` (Node 24) — **7 passed**. Tests cover case-insensitive search, composed filters, absent indicators, numeric ordering, nulls last in both directions, zero-valued funding, ineligible coverage, no mutation and empty results. Test fixtures never feed the UI.
- Real in-app Chromium browser against existing localhost frontend/API: 20 assets, 16 eligible, auto-entry disabled; TRON historical LONG rejection displayed exact engine reason `execution gated: auto-entry disabled in settings`.
- Search for TRON returns one asset; ineligible filter returns four, including Figure Heloc with exact reason `no linear perp market on configured exchanges`.
- Volume sort places BTC/ETH/SOL first; ≥$10B volume filter returns two; uptrend filter returns four; adding candidate filter returns the empty state. Reset restores all 20.
- BTC public candles loaded in the mobile drawer. TRON decision and chart inspected on desktop. Timeframe controls use keyed chart instances to avoid showing the previous symbol/timeframe during loading.
- Viewports checked: 1440×1000, 1100×900, 768×1024, 390×844. No document horizontal overflow at tablet/mobile; table scroll stays inside its region. Mobile drawer width equals viewport width. Mobile safety banner wraps rather than clipping.
- Semantic labels, table caption/sort state, native filter controls, focusable scroll region, named dialog and Escape dismissal with focus restored to the selected asset inspected. Browser console showed no application warnings/errors during checks. This is not a full screen-reader or automated accessibility audit.

## Limits / remaining issues

- API does not provide independent quote/funding/spread timestamps or per-asset evaluation timestamps. UI labels the available global cycle and snapshot times, and discloses missing provenance rather than deriving false freshness.
- Decision history is limited to the latest 200 global records, showing up to five for the selected instrument. Absence is not presented as rejection. Accepted records may lack a detailed approval explanation; that limitation is explicit.
- Ineligible assets have no verified chart symbol, so their panel explains why a chart is unavailable.
- Charts use the existing cached public candle endpoint; its cache retrieval timestamp is not exposed. Last candle opening time is shown and forming candles are identified as possible.
- Wide metric tables intentionally scroll horizontally on smaller screens. No row sparklines were fabricated; chart inspection is on demand in the asset panel.
- Default Turbopack production build remains environment-blocked; webpack production build is verified. Offline, stale and accepted-decision branches are implemented but were not forced against the running engine during browser QA.

## Screenshots

See `screens/scanner-upgrade/`: desktop, tablet, mobile and asset-analysis captures. These are real stored market snapshots, not demo fixtures. Browser verification used the running development frontend; production compilation was verified separately.
