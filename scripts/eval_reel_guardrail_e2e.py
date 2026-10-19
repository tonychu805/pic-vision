"""E2E: the real reel pipeline (detect -> rank -> top-N) with the Jev guardrail wired into selection (2026-10-19, PIC-226).
DRY run only: the Jev verdicts come from the already-saved results (cache/jev_rally/results.jsonl), so NO footage is
sent to TypeSafe. It reports both the reel effect and the time/tokens that were recorded when those Jev calls were made.

The LIVE path (Jev called on fresh footage inside the pipeline) is NOT in this script, by design: sending PGC footage to
TypeSafe is the operator's to run, not the agent's. Live Jev runs go through `scripts/eval_jev_rally.py`, which records
`sec` and token usage per call; the time/cost summary here (cost_report) reads those same fields, so a live run is
measured the same way. See that script to run live.

Pipeline per session CSV (same as summarise_top_sample / the shipped path):
  validate_absolute_ranking.detect -> src.select.score_segments -> top-N ranked rallies (what the reel is built from).
GUARDRAIL: drop a candidate when its Jev "real" score < CUT. A candidate with no score is KEPT (conservative). CUT=0.4.
TRUTH for scoring the reel: the operator's playback verdicts (summarise_top_sample.v): real / short / not.
TIME + COST: each Jev call's wall seconds and input/output tokens are the hard record. Dollars are computed only from a
  rate you set (TYPESAFE_PRICE_IN_PER_M / TYPESAFE_PRICE_OUT_PER_M, $ per 1M tokens, from the TypeSafe billing page) —
  the lone historical $0.00035/call estimate (EXPERIMENTS 2026-10-17) is too rough to assert here.
Run: .venv/bin/python scripts/eval_reel_guardrail_e2e.py [N] [CUT]
"""
import collections, glob, json, os, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import summarise_top_sample as S
from src.select import net_width_px, score_segments

DIR = "cache/pgc_fieldtest"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
N = int(args[0]) if len(args) > 0 else 5
CUT = float(args[1]) if len(args) > 1 else 0.4
PRICE_IN = float(os.environ["TYPESAFE_PRICE_IN_PER_M"]) if os.environ.get("TYPESAFE_PRICE_IN_PER_M") else None
PRICE_OUT = float(os.environ.get("TYPESAFE_PRICE_OUT_PER_M", "0")) if os.environ.get("TYPESAFE_PRICE_IN_PER_M") else None
JEV = {json.loads(l)["id"]: json.loads(l) for l in open("cache/jev_rally/results.jsonl")}


def cost_report(records, live):
    """records: list of dicts with 'sec' and 'tok' (input tokens); live adds 'otok' (output). Prints the hard record
    (time + tokens) and a $ figure only if a price rate is set in the environment."""
    r = [x for x in records if x.get("sec") is not None and x.get("tok") is not None]
    if not r:
        print("\nTIME/COST: no per-call time or token data available."); return
    secs = [x["sec"] for x in r]; itok = sum(x["tok"] for x in r); otok = sum(x.get("otok", 0) for x in r)
    tot = sum(secs)
    print(f"\nTIME/COST ({'LIVE this run' if live else 'recorded per Jev call in cache/jev_rally/results.jsonl'}):")
    print(f"  calls {len(r)}  |  wall time total {tot:.1f}s ({tot/60:.1f} min), mean {tot/len(r):.2f}s, max {max(secs):.2f}s")
    print(f"  input tokens total {itok:,} (mean {itok//len(r):,}/call)" + (f"; output tokens total {otok:,}" if live else ""))
    print(f"  projection: per session (top-{N}) ~{N*tot/len(r):.1f}s and ~{N*itok//len(r):,} input tok; "
          f"scales with #candidate rallies, NOT footage length (sparse: one call per reel candidate)")
    if PRICE_IN is not None:
        dollars = itok / 1e6 * PRICE_IN + otok / 1e6 * (PRICE_OUT or 0)
        print(f"  cost @ ${PRICE_IN}/1M in" + (f" + ${PRICE_OUT}/1M out" if PRICE_OUT else "") +
              f": ${dollars:.4f} total, ${dollars/len(r):.5f}/call, ~${N*dollars/len(r):.4f}/session")
    else:
        print("  cost $: set TYPESAFE_PRICE_IN_PER_M (and _OUT_PER_M) to the TypeSafe billing rate to compute dollars; "
              "tokens above x your rate otherwise.")


def verdict(sid, s):
    m = [val for (ks, a, b), val in S.v.items() if ks == sid and S.ov(s["start"], s["end"], a, b)]
    return m[0][0] if m else "missing"


def main():
    reel = []
    for p in sorted(glob.glob(f"{DIR}/*.csv")):
        sid = os.path.basename(p)[:-4]
        try:
            calib = json.load(open(f"{DIR}/{sid}.calib.json"))
        except FileNotFoundError:
            continue
        segs, cr, sp = S.base.detect(p, calib)
        top = score_segments(segs, cr, sp, net_width_px(calib))[:N]
        for rank, s in enumerate(top, 1):
            jid = f"{sid[:8]}_{s['start']:.2f}"; j = JEV.get(jid)
            reel.append(dict(sid=sid[:8], rank=rank, start=s["start"], v=verdict(sid, s),
                             jev=None if j is None else j["real"], kind=None if j is None else j.get("kind"),
                             sec=None if j is None else j.get("sec"), tok=None if j is None else j.get("tok")))
    dec = [r for r in reel if r["v"] in ("real", "short", "not")]
    kept = lambda r: r["jev"] is None or r["jev"] >= CUT
    cov = sum(r["jev"] is not None for r in reel)
    print(f"reel candidates (top-{N}/session): {len(reel)}; Jev-scored {cov}/{len(reel)}; operator-decided {len(dec)}")

    def share(rows):
        real = sum(r["v"] == "real" for r in rows); sh = sum(r["v"] == "short" for r in rows); no = sum(r["v"] == "not" for r in rows)
        return real, sh, no, len(rows)

    for label, rows in (("BEFORE guardrail", dec), (f"AFTER guardrail (Jev real>={CUT})", [r for r in dec if kept(r)])):
        real, sh, no, n = share(rows)
        print(f"\n{label}: {n} clips  |  real {real} ({real/max(1,n):.0%})  short {sh}  not {no}"
              + (f"  real-among-nonshort {real/max(1,real+no):.0%}" if real + no else ""))
    dropped = [r for r in dec if not kept(r)]
    print(f"\nguardrail dropped {len(dropped)}: "
          f"not {sum(r['v']=='not' for r in dropped)}, short {sum(r['v']=='short' for r in dropped)}, real {sum(r['v']=='real' for r in dropped)}")
    for r in sorted(dropped, key=lambda r: r["jev"]):
        print(f"  drop {r['sid']} rank{r['rank']} start {r['start']:.1f}  verdict={r['v']:5s} jev={r['jev']:.2f} kind={r['kind']}")
    print("\nby rank (real-share, before -> after):")
    for rk in range(1, N + 1):
        b = [r for r in dec if r["rank"] == rk]; a = [r for r in b if kept(r)]
        rb = sum(x["v"] == "real" for x in b); ra = sum(x["v"] == "real" for x in a)
        if b: print(f"  rank {rk}: {rb}/{len(b)} ({rb/len(b):.0%}) -> {ra}/{len(a)} ({ra/max(1,len(a)):.0%})")
    cost_report(reel, live=False)


if __name__ == "__main__":
    main()
