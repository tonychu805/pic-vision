"""E2E: the real reel pipeline (detect -> rank -> top-N) with the Jev guardrail wired into selection (2026-10-19, PIC-226).
Dry run: the Jev verdicts come from the already-saved results (cache/jev_rally/results.jsonl), so NO footage is sent to
TypeSafe. This exercises the live selection pipeline end to end and measures what the Jev guardrail does to the reel.

Pipeline per session CSV (same as summarise_top_sample / the shipped path):
  validate_absolute_ranking.detect -> src.select.score_segments -> top-N ranked rallies (what the reel is built from).
GUARDRAIL: drop a candidate when its saved Jev "real" score < CUT. A candidate with no saved Jev score is KEPT
  (conservative: the guardrail only removes what it has judged). CUT = 0.4 (the frozen Test L cut-off).
TRUTH for scoring the reel: the operator's playback verdicts (summarise_top_sample.v): real / short / not.
REPORTED: reel real-share before vs after the guardrail, junk removed, real/short removed, Jev coverage; per rank.
Not a held-out test (Jev scores and verdicts are already known) — an integration e2e of the new selection path.
Run: .venv/bin/python scripts/eval_reel_guardrail_e2e.py [N] [CUT]
"""
import collections, glob, json, os, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import summarise_top_sample as S
from src.select import net_width_px, score_segments

DIR = "cache/pgc_fieldtest"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
CUT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.4
JEV = {json.loads(l)["id"]: json.loads(l) for l in open("cache/jev_rally/results.jsonl")}


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
                             jev=None if j is None else j["real"], kind=None if j is None else j.get("kind")))
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


if __name__ == "__main__":
    main()
