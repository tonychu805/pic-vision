"""Score the operator's verdicts on the top-5-per-session field sample (PIC-226).
Combines the 40 new clips (101-140, cache/top_sample_key.csv) with the 30 top-5
slots that were already judged in earlier samples. Reads verdicts typed below.
"""
import collections, csv, glob, json, math, os, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import validate_absolute_ranking as base
from src.select import net_width_px, score_segments
DIR = "cache/pgc_fieldtest"
def sid_of(p): return [x.split("/")[-1][:-4] for x in glob.glob(f"{DIR}/*.csv") if x.split("/")[-1].startswith(p)][0]
v = {}
bk = {r["clip"]: r for r in csv.DictReader(open("cache/blind_check_key.csv"))}
for c in "KLNPQR": r = bk[c]; v[(sid_of(r["video"].split(":")[-1]), float(r["start"]), float(r["end"]))] = ("real", "")
for c in "OM": r = bk[c]; v[(sid_of(r["video"].split(":")[-1]), float(r["start"]), float(r["end"]))] = ("not", "sunlight" if c == "O" else "tossed ball")
fk = {r["clip"]: r for r in csv.DictReader(open("cache/flag_check_key.csv"))}
for c, x in {"S": "not", "T": "real", "U": "not", "V": "not", "W": "not", "X": "real", "Y": "real", "Z": "not"}.items():
    r = fk[c]; v[(sid_of(r["session"]), float(r["start"]), float(r["end"]))] = (x, "")
pk = {r["clip"]: r for r in csv.DictReader(open("cache/precision_sample_key.csv"))}
REAL = {"01","02","04","05","06","08","10","11","12","13","16","17","19","20","22","23","25","27","28","31","32","33","34","38"}
SHORT = {"07", "14", "15", "40"}; UNSURE = {"35"}
why = {"03":"ball machine","21":"ball machine","30":"ball machine","36":"ball machine","18":"warm-up","24":"warm-up","26":"warm-up","37":"warm-up","39":"warm-up","29":"feeding","09":"serve out"}
for c, r in pk.items():
    x = "real" if c in REAL else "short" if c in SHORT else "unsure" if c in UNSURE else "not"
    v[(sid_of(r["session"]), float(r["start"]), float(r["end"]))] = (x, why.get(c, ""))
new = ("101=real,102=short,103=real,104=real,105=real,106=real,107=real,108=not,109=short,110=real,111=real,112=not,113=short,114=real,115=real,"
       "116=real,117=real,118=not,119=short,120=real,121=real,122=real,123=real,124=not,125=not,126=real,127=real,128=real,129=real,130=real,"
       "131=real,132=not,133=short,134=real,135=real,136=real,137=real,138=short,139=real,140=not")
newv = dict(x.split("=") for x in new.split(","))
newwhy = {"108": "warm-up/practice", "112": "ball machine", "118": "warm-up/practice", "132": "warm-up/practice", "140": "ball machine", "124": "not given", "125": "not given"}
tk = {r["clip"]: r for r in csv.DictReader(open("cache/top_sample_key.csv"))}
for c, r in tk.items():
    v[(sid_of(r["session"]), float(r["start"]), float(r["end"]))] = (newv[c], newwhy.get(c, ""))
def ov(a0, a1, b0, b1):
    i = max(0, min(a1, b1) - max(a0, b0)); return i / max(1e-6, (a1 - a0) + (b1 - b0) - i) >= 0.5
slots = []
for p in sorted(glob.glob(f"{DIR}/*.csv")):
    sid = os.path.basename(p)[:-4]; calib = json.load(open(f"{DIR}/{sid}.calib.json"))
    segs, cr, sp = base.detect(p, calib)
    for rank, s in enumerate(score_segments(segs, cr, sp, net_width_px(calib))[:5], 1):
        m = [val for (ks, a, b), val in v.items() if ks == sid and ov(s["start"], s["end"], a, b)]
        slots.append((sid[:8], rank, m[0] if m else ("missing", "")))
dec = [s for s in slots if s[2][0] in ("real", "short", "not")]
n = len(dec); real = sum(s[2][0] == "real" for s in dec); sh = sum(s[2][0] == "short" for s in dec); no = sum(s[2][0] == "not" for s in dec)
p_ = real / n; ci = 1.96 * math.sqrt(p_ * (1 - p_) / n)
print(f"top-5 slots {len(slots)}, judged {n}")
print(f"real {real} ({p_:.0%}, 95% {max(0,p_-ci):.0%}-{min(1,p_+ci):.0%}); very short {sh}; not a rally {no}; if very short counted real {(real+sh)/n:.0%}")
print("bar >= 80% real:", "MET" if p_ >= 0.8 else "NOT met")
for r in range(1, 6):
    d = [s for s in dec if s[1] == r]; rl = sum(s[2][0] == "real" for s in d); print(f"  rank {r}: {rl}/{len(d)} real ({rl/len(d):.0%})")
top3 = [s for s in dec if s[1] <= 3]; print(f"  ranks 1-3: {sum(s[2][0]=='real' for s in top3)}/{len(top3)} real ({sum(s[2][0]=='real' for s in top3)/len(top3):.0%})")
c = collections.Counter(("serve + return only" if s[2][0] == "short" else (s[2][1] or "not given")) for s in dec if s[2][0] in ("short", "not"))
print("not real, by kind:", dict(c.most_common()))
prac = sum(v_ for k, v_ in c.items() if any(t in k for t in ("machine", "warm", "feeding", "practice")))
print(f"practice-type: {prac} of {sum(c.values())} not-real")
