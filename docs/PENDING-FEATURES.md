# Pending / not-yet-implemented features

These are requested but **NOT implemented**. They must not be claimed as done.

## Hybrid 50%-at-2R profit-taking (PENDING)
- **Requested:** close 50% of a position at 2R (twice the initial planned risk),
  then trail the remaining 50%.
- **Status:** NOT IMPLEMENTED. The engines currently open every position with
  `with_target=False` (no fixed target) and exit the FULL position in one
  settlement via trailing stop / liquidation / emergency exit. There is no
  partial-exit code path, so a "duplicate 2R partial take-profit" is
  structurally impossible today.
- **Design implications when implemented:** partial exits must reduce qty +
  release a proportional margin + realize partial P&L exactly once (same
  settlements-table idempotency discipline, keyed per partial-fill), must
  never allow a second 50%-at-2R on the same leg, and the reconciliation
  identity must be extended to account for partially-closed positions.
