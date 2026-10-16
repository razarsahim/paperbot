"use client";

import { useState } from "react";
import { PriceChart } from "@/components/charts/price-chart";
import { getCandles } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { fmtDateTime, fmtNum, fmtPct, fmtPrice } from "@/lib/format";
import { trendLabel } from "@/lib/scanner";
import type { SignalEvent, UniverseAsset } from "@/lib/types";

function AssetChart({ symbol, tf }: { symbol: string; tf: string }) {
  const result = usePoll(() => getCandles(symbol, tf, 160), 30_000, [
    symbol,
    tf,
  ]);
  if (result.loading)
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Loading public candles…
      </div>
    );
  if (result.source !== "live" || !result.data?.candles.length)
    return (
      <p className="rounded-lg border border-dashed p-8 text-muted-foreground">
        Chart unavailable. No synthetic candles are displayed.
      </p>
    );
  return (
    <div>
      <PriceChart data={result.data} height={300} />
      <p className="mt-2 text-xs text-muted-foreground">
        Last candle opens {fmtDateTime(result.data.candles.at(-1)?.[0])}. The
        latest candle may still be forming. Cache retrieval time is not provided
        by this API.
      </p>
    </div>
  );
}

export function ScannerAnalysis({
  asset: a,
  events,
  logAvailable,
  scanMs,
}: {
  asset: UniverseAsset;
  events: SignalEvent[];
  logAvailable: boolean;
  scanMs?: number | null;
}) {
  const [tf, setTf] = useState("1h");
  const history = events
    .filter((e) => e.symbol === a.instrument?.symbol)
    .sort((a, b) => b.ts_ms - a.ts_ms)
    .slice(0, 5);
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <span className="text-3xl font-semibold tracking-tight tabular-nums">
          {fmtPrice(a.price_usd)}
        </span>
        <span className="text-sm text-muted-foreground">
          Market snapshot · USD
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {[
          ["EMA trend", trendLabel(a)],
          [
            "Strategy candidate",
            a.signal === "long" || a.signal === "short"
              ? a.signal.toUpperCase()
              : "None reported",
          ],
          ["RSI", fmtNum(a.rsi, 1)],
          ["ATR / price", fmtPct(a.atr_pct)],
          [
            "Funding rate",
            fmtPct(
              a.instrument?.funding_rate == null
                ? null
                : a.instrument.funding_rate * 100,
              4,
              true,
            ),
          ],
          ["Spread", fmtPct(a.instrument?.spread_pct, 3)],
        ].map(([label, value]) => (
          <div key={label} className="rounded-lg border bg-muted/20 p-3">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="mt-1 font-medium tabular-nums">{value}</p>
          </div>
        ))}
      </div>
      <section className="rounded-xl border p-4">
        <h3 className="font-semibold">
          {a.eligible ? "Instrument eligible" : "Instrument ineligible"}
        </h3>
        <p className="mt-2 text-sm text-muted-foreground">
          {a.reason ||
            (a.eligible
              ? "Verified instrument metadata. Eligibility does not approve an entry."
              : "No reason supplied by the engine.")}
        </p>
        {a.instrument && (
          <p className="mt-2 text-xs text-muted-foreground">
            {a.instrument.exchange} · {a.instrument.symbol} · taker fee{" "}
            {fmtPct(a.instrument.taker_fee * 100, 3)} · mark{" "}
            {fmtPrice(a.instrument.mark_price)}
          </p>
        )}
      </section>
      <section>
        <h3 className="font-semibold">Price analysis</h3>
        {a.instrument ? (
          <>
            <div
              className="my-3 flex flex-wrap gap-2"
              aria-label="Chart timeframe"
            >
              {["5m", "15m", "1h", "4h", "1d"].map((t) => (
                <button
                  key={t}
                  onClick={() => setTf(t)}
                  aria-pressed={tf === t}
                  className={`rounded-md border px-3 py-2 text-xs ${tf === t ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
                >
                  {t}
                </button>
              ))}
            </div>
            <AssetChart
              key={`${a.instrument.symbol}:${tf}`}
              symbol={a.instrument.symbol}
              tf={tf}
            />
            <p className="mt-2 text-xs text-muted-foreground">
              Scroll to zoom · drag to pan · crosshair to inspect. EMA20 / EMA50
              overlays are chart calculations, not entry approvals.
            </p>
          </>
        ) : (
          <p className="mt-3 rounded-lg border border-dashed p-5 text-muted-foreground">
            No verified instrument mapping available for a price chart.
          </p>
        )}
      </section>
      <section>
        <h3 className="font-semibold">Recorded entry decisions</h3>
        <p className="my-2 text-xs text-muted-foreground">
          Historical audit records, not current opportunities. Trend describes
          EMA direction; a candidate still requires all execution and risk
          gates.
        </p>
        {!logAvailable ? (
          <p>Decision log unavailable.</p>
        ) : !history.length ? (
          <p className="text-sm text-muted-foreground">
            No decision for this instrument in the latest 200 records. No
            acceptance or rejection is inferred.
          </p>
        ) : (
          <ul className="space-y-3">
            {history.map((e, i) => (
              <li key={`${e.ts_ms}:${i}`} className="rounded-lg border p-3">
                <div className="flex flex-wrap justify-between gap-2">
                  <strong
                    className={
                      e.approved
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-amber-700 dark:text-amber-300"
                    }
                  >
                    {e.action.toUpperCase()} ·{" "}
                    {e.approved ? "Accepted" : "Rejected"}
                  </strong>
                  <time className="text-xs text-muted-foreground">
                    {fmtDateTime(e.ts_ms)}
                  </time>
                </div>
                <p className="mt-2 text-sm">
                  {e.reject_reason ||
                    (e.approved
                      ? "Approved by the engine risk governor; no further approval reason supplied."
                      : "No rejection reason supplied.")}
                </p>
                {e.details && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {e.details}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      <div className="border-t pt-4 text-xs leading-relaxed text-muted-foreground">
        <p>Scanner cycle: {fmtDateTime(scanMs)}</p>
        <p>
          Candle cache age at evaluation:{" "}
          {a.instrument?.data_age_s == null
            ? "unavailable"
            : `${fmtNum(a.instrument.data_age_s, 0)} seconds`}
          . This is not the current quote age.
        </p>
        <p>
          Funding and spread are stored evaluation snapshots. Their individual
          timestamps are unavailable.
        </p>
      </div>
    </div>
  );
}
