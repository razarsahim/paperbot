import assert from "node:assert/strict";
import { test } from "node:test";
import {
  selectAssets,
  defaultFilters,
  trendLabel,
} from "../src/lib/scanner.ts";
// Deliberately artificial unit fixtures; never used by the dashboard.
const base = {
  name: "Test asset",
  symbol: "TEST",
  rank: 1,
  price_usd: 2,
  volume_24h_usd: 200000000,
  eligible: true,
  trend: "up",
  rsi: 50,
  atr_pct: 1,
  signal: null,
  instrument: { funding_rate: 0, spread_pct: 0 },
};
const rows = [
  base,
  {
    ...base,
    name: "Other",
    symbol: "OTHER",
    rank: 2,
    rsi: null,
    atr_pct: null,
    eligible: false,
    instrument: null,
  },
  {
    ...base,
    name: "Third",
    symbol: "THIRD",
    rank: 3,
    signal: "long",
    price_usd: 5,
    volume_24h_usd: 2000000000,
  },
];
test("search is trimmed and case insensitive", () =>
  assert.deepEqual(
    selectAssets(rows, { ...defaultFilters, search: " test " }, "rank", false),
    [base],
  ));
test("filters compose without confusing trend with candidate", () =>
  assert.equal(
    selectAssets(
      rows,
      {
        ...defaultFilters,
        trend: "Uptrend",
        signal: "candidate",
        eligibility: "eligible",
        volume: "1000000000",
      },
      "rank",
      false,
    )[0].symbol,
    "THIRD",
  ));
test("missing indicators are unavailable, not flat", () =>
  assert.equal(trendLabel(rows[1]), "Unavailable"));
test("numeric sorting, nulls last in both directions and no mutation", () => {
  for (const desc of [false, true])
    assert.equal(
      selectAssets(rows, defaultFilters, "rsi", desc).at(-1).symbol,
      "OTHER",
    );
  assert.equal(
    selectAssets(rows, defaultFilters, "price_usd", true)[0].symbol,
    "THIRD",
  );
  assert.equal(rows[0], base);
});
test("zero funding and spread stay valid values", () =>
  assert.equal(
    selectAssets(rows, defaultFilters, "funding_rate", false).at(-1).symbol,
    "OTHER",
  ));
test("eligibility and unavailable filters preserve excluded assets", () =>
  assert.equal(
    selectAssets(
      rows,
      { ...defaultFilters, eligibility: "ineligible", trend: "Unavailable" },
      "rank",
      false,
    ).length,
    1,
  ));
test("no matches returns empty list", () =>
  assert.equal(
    selectAssets(rows, { ...defaultFilters, search: "missing" }, "rank", false)
      .length,
    0,
  ));
