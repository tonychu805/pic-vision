# Evaluation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the scoring harness that reads predicted rallies + hand-labeled rallies and prints the two PRD §5 tables (detection + selection), proven correct against hand-written stubs before any detector exists (PRD Phase 0 exit criterion).

**Architecture:** Pure interval math, no video. A small set of functions turn two lists of time-intervals — predictions and ground-truth labels — into metric numbers. A thin file-reading + printing layer wraps them into a `python3 -m eval.harness` command and a `make eval` target. The logic functions take plain Python lists so tests can check them with hand-computed numbers, no files needed.

**Tech Stack:** Python 3 (standard library only for the harness itself — `json`, `argparse`, `statistics`). `pytest` as a dev-only dependency for tests.

## Global Constraints

- **Runtime deps:** standard library only. The harness never opens video (TECH_SPEC §11.3: "reads `rallies.json`, never rendered video"). `pytest` is dev-only.
- **Run Python with `python3`** — plain `python` is not on this machine's PATH.
- **Matching (TECH_SPEC §11.2, verbatim):** temporal `IoU = overlap / (dur_pred + dur_gt - overlap)`; match at `IoU >= 0.5`; **one-to-one assignment, greedy by descending IoU**. Leftover labels are misses; leftover predictions are false positives.
- **Detection metrics ignore the `selected` field; selection metrics read it** (TECH_SPEC §11.3).
- **Highlight budget = 600 seconds, hard** (PRD §5).
- **All times are in seconds** (floats).
- **`rallies.json` schema** (predictions, self-describing):
  ```json
  { "source_duration_sec": 1200,
    "rallies": [ {"start": 12.0, "end": 18.5, "selected": true, "score": 0.9} ] }
  ```
  `start`, `end`, `selected` required; `score` optional and ignored by this slice.
- **Label schema** (ground truth, one JSON object per line — the existing `label.py` output): `{"start": .., "end": .., "duration": .., "rally_id": ..}`. The harness reads only `start`/`end`.

---

## File Structure

- `eval/__init__.py` — makes `eval` an importable package so `python3 -m eval.harness` works. Empty.
- `eval/harness.py` — the whole harness: matching, both metric groups, file I/O, CLI.
- `tests/test_harness.py` — all tests, with hand-computed expected numbers.
- `Makefile` — `make eval` and `make test` targets (TECH_SPEC §13 references `make eval`).
- `requirements.txt` — add a dev section with `pytest` (modify existing file).

One module holds all the harness logic because the pieces are small, share the interval representation, and always change together. Splitting them across files would add navigation cost with no isolation benefit.

---

### Task 1: Project setup + temporal IoU

Sets up the test tooling and builds the smallest piece: the overlap score between two time-intervals. Everything else is built on this.

**Files:**
- Create: `eval/__init__.py` (empty)
- Create: `eval/harness.py`
- Create: `tests/test_harness.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `iou(a, b) -> float` where `a` and `b` are dicts with `"start"` and `"end"` float keys. Returns overlap-over-union in [0, 1]; `0.0` when the intervals don't overlap.

- [ ] **Step 1: Add pytest as a dev dependency**

Append to `requirements.txt`:

```
# dev only
pytest
```

- [ ] **Step 2: Make `eval` an importable package**

Create `eval/__init__.py` as an empty file:

```python
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_harness.py`:

```python
from eval.harness import iou


def test_iou_identical_intervals_is_one():
    assert iou({"start": 0.0, "end": 10.0}, {"start": 0.0, "end": 10.0}) == 1.0


def test_iou_half_overlap():
    # overlap = 5, union = 10 + 10 - 5 = 15  ->  5/15 = 0.3333...
    result = iou({"start": 0.0, "end": 10.0}, {"start": 5.0, "end": 15.0})
    assert abs(result - (1.0 / 3.0)) < 1e-9


def test_iou_no_overlap_is_zero():
    assert iou({"start": 0.0, "end": 10.0}, {"start": 20.0, "end": 30.0}) == 0.0
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python3 -m pytest tests/test_harness.py -v`
Expected: FAIL — `ImportError: cannot import name 'iou'` (or `ModuleNotFoundError`).

- [ ] **Step 5: Write the minimal implementation**

Create `eval/harness.py`:

```python
"""Evaluation harness (TECH_SPEC §11). Scores predicted rallies against
hand-labeled rallies and prints the two PRD §5 tables. Reads JSON only,
never video."""


def iou(a, b):
    """Temporal intersection-over-union of two intervals.

    Each interval is a dict with float 'start' and 'end' (seconds).
    Returns overlap / union in [0, 1]; 0.0 when they do not overlap.
    """
    overlap = min(a["end"], b["end"]) - max(a["start"], b["start"])
    if overlap <= 0.0:
        return 0.0
    union = (a["end"] - a["start"]) + (b["end"] - b["start"]) - overlap
    return overlap / union
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python3 -m pytest tests/test_harness.py -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add eval/__init__.py eval/harness.py tests/test_harness.py requirements.txt
git commit -m "feat(eval): temporal IoU + pytest setup"
```

---

### Task 2: Greedy one-to-one matching

Decides which predicted rallies count as "found" a labeled rally. The key rule (TECH_SPEC §11.2): a single prediction can't take credit for two labels. Greedy-by-best-overlap enforces that.

**Files:**
- Modify: `eval/harness.py`
- Modify: `tests/test_harness.py`

**Interfaces:**
- Consumes: `iou` from Task 1.
- Produces: `match_intervals(preds, gts, threshold=0.5) -> dict` with keys:
  - `"matches"`: list of `(pred_index, gt_index, iou_value)` tuples
  - `"missed"`: list of gt indices with no match
  - `"false_pos"`: list of pred indices with no match
  `preds` and `gts` are lists of interval dicts (`start`/`end`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_harness.py`:

```python
from eval.harness import match_intervals


def test_match_perfect_one_to_one():
    preds = [{"start": 0.0, "end": 10.0}]
    gts = [{"start": 0.0, "end": 10.0}]
    result = match_intervals(preds, gts)
    assert len(result["matches"]) == 1
    assert result["missed"] == []
    assert result["false_pos"] == []


def test_match_one_prediction_cannot_claim_two_labels():
    # pred spans both labels; IoU with each is exactly 0.5 (>= threshold),
    # but greedy one-to-one must credit only ONE. The other is a miss.
    preds = [{"start": 0.0, "end": 20.0}]
    gts = [{"start": 0.0, "end": 10.0}, {"start": 10.0, "end": 20.0}]
    result = match_intervals(preds, gts)
    assert len(result["matches"]) == 1
    assert len(result["missed"]) == 1
    assert result["false_pos"] == []


def test_match_reports_miss_and_false_positive():
    preds = [{"start": 0.0, "end": 10.0}, {"start": 200.0, "end": 210.0}]
    gts = [{"start": 0.0, "end": 10.0}, {"start": 100.0, "end": 110.0}]
    result = match_intervals(preds, gts)
    assert len(result["matches"]) == 1
    assert result["missed"] == [1]      # gt at 100-110 unmatched
    assert result["false_pos"] == [1]   # pred at 200-210 unmatched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_harness.py -k match -v`
Expected: FAIL — `cannot import name 'match_intervals'`.

- [ ] **Step 3: Write the implementation**

Add to `eval/harness.py`:

```python
def match_intervals(preds, gts, threshold=0.5):
    """Greedy one-to-one temporal matching (TECH_SPEC §11.2).

    Considers every prediction/label pair whose IoU meets the threshold,
    then accepts them best-overlap-first, never reusing a prediction or a
    label. Returns matches, unmatched labels (misses), and unmatched
    predictions (false positives).
    """
    candidates = []
    for pi, p in enumerate(preds):
        for gi, g in enumerate(gts):
            score = iou(p, g)
            if score >= threshold:
                candidates.append((score, pi, gi))
    candidates.sort(reverse=True)  # highest IoU first

    used_pred, used_gt, matches = set(), set(), []
    for score, pi, gi in candidates:
        if pi in used_pred or gi in used_gt:
            continue
        matches.append((pi, gi, score))
        used_pred.add(pi)
        used_gt.add(gi)

    missed = [gi for gi in range(len(gts)) if gi not in used_gt]
    false_pos = [pi for pi in range(len(preds)) if pi not in used_pred]
    return {"matches": matches, "missed": missed, "false_pos": false_pos}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_harness.py -k match -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add eval/harness.py tests/test_harness.py
git commit -m "feat(eval): greedy one-to-one interval matching"
```

---

### Task 3: Detection metrics

Turns the match result into the three detection numbers the harness can compute from intervals alone: recall, false positives per 10 minutes, and median boundary error. (The fourth PRD detection metric, wall-clock ratio, is a pipeline-runtime measurement and is out of scope here.)

**Files:**
- Modify: `eval/harness.py`
- Modify: `tests/test_harness.py`

**Interfaces:**
- Consumes: `match_intervals` from Task 2.
- Produces: `detection_metrics(preds, gts, source_duration_sec) -> dict` with keys:
  `"recall"` (float), `"false_pos_per_10min"` (float), `"boundary_error_median_sec"` (float), `"n_labeled"` (int), `"n_pred"` (int), `"n_matched"` (int).
  Boundary error = median of the pooled absolute start-errors and end-errors over all matched pairs.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_harness.py`:

```python
from eval.harness import detection_metrics


def test_detection_perfect_run():
    preds = [{"start": 0.0, "end": 10.0}]
    gts = [{"start": 0.0, "end": 10.0}]
    m = detection_metrics(preds, gts, source_duration_sec=600.0)
    assert m["recall"] == 1.0
    assert m["false_pos_per_10min"] == 0.0
    assert m["boundary_error_median_sec"] == 0.0


def test_detection_recall_and_false_positive_rate():
    # 2 labels, 1 matched -> recall 0.5.
    # 1 false prediction over 1200 s of source -> 1 / (1200/600) = 0.5 per 10 min.
    preds = [{"start": 0.0, "end": 10.0}, {"start": 200.0, "end": 210.0}]
    gts = [{"start": 0.0, "end": 10.0}, {"start": 100.0, "end": 110.0}]
    m = detection_metrics(preds, gts, source_duration_sec=1200.0)
    assert m["recall"] == 0.5
    assert m["false_pos_per_10min"] == 0.5


def test_detection_boundary_error_median():
    # matched pair off by 1 s at each end -> pooled errors [1, 1] -> median 1.0
    preds = [{"start": 1.0, "end": 11.0}]
    gts = [{"start": 0.0, "end": 10.0}]
    m = detection_metrics(preds, gts, source_duration_sec=600.0)
    assert m["boundary_error_median_sec"] == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_harness.py -k detection -v`
Expected: FAIL — `cannot import name 'detection_metrics'`.

- [ ] **Step 3: Write the implementation**

Add the import at the top of `eval/harness.py` (below the module docstring):

```python
import statistics
```

Add the function to `eval/harness.py`:

```python
def detection_metrics(preds, gts, source_duration_sec):
    """Detection table (PRD §5). Ignores the 'selected' field.

    - recall: matched labels / all labels
    - false_pos_per_10min: unmatched predictions, normalized to 10 minutes
    - boundary_error_median_sec: median of the absolute start- and end-time
      errors across matched pairs
    """
    m = match_intervals(preds, gts)
    n_labeled, n_pred, n_matched = len(gts), len(preds), len(m["matches"])

    recall = n_matched / n_labeled if n_labeled else 0.0
    fp_per_10min = (
        len(m["false_pos"]) / (source_duration_sec / 600.0)
        if source_duration_sec else 0.0
    )

    errors = []
    for pi, gi, _ in m["matches"]:
        errors.append(abs(preds[pi]["start"] - gts[gi]["start"]))
        errors.append(abs(preds[pi]["end"] - gts[gi]["end"]))
    boundary_error = statistics.median(errors) if errors else 0.0

    return {
        "recall": recall,
        "false_pos_per_10min": fp_per_10min,
        "boundary_error_median_sec": boundary_error,
        "n_labeled": n_labeled,
        "n_pred": n_pred,
        "n_matched": n_matched,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_harness.py -k detection -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add eval/harness.py tests/test_harness.py
git commit -m "feat(eval): detection metrics (recall, FP/10min, boundary error)"
```

---

### Task 4: Selection metrics

Turns the `selected` subset of predictions into the reel numbers: is it within the 10-minute budget, how full is the budget, how many rallies, and what fraction of detected rallies were kept.

**Files:**
- Modify: `eval/harness.py`
- Modify: `tests/test_harness.py`

**Interfaces:**
- Produces: `selection_metrics(preds, budget_sec=600.0) -> dict` with keys:
  `"selected_duration_sec"` (float), `"budget_compliant"` (bool), `"utilization"` (float), `"rally_count"` (int), `"keep_rate"` (float).
  Reads each prediction's `"selected"` flag (missing/false = not selected).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_harness.py`:

```python
from eval.harness import selection_metrics


def test_selection_within_budget():
    # selected durations 200 + 300 = 500 s of a 600 s budget
    preds = [
        {"start": 0.0, "end": 200.0, "selected": True},
        {"start": 200.0, "end": 500.0, "selected": True},
        {"start": 500.0, "end": 600.0, "selected": False},
    ]
    m = selection_metrics(preds)
    assert m["selected_duration_sec"] == 500.0
    assert m["budget_compliant"] is True
    assert abs(m["utilization"] - (500.0 / 600.0)) < 1e-9
    assert m["rally_count"] == 2
    assert abs(m["keep_rate"] - (2.0 / 3.0)) < 1e-9


def test_selection_over_budget_is_not_compliant():
    # selected durations 400 + 300 = 700 s -> over the 600 s hard budget
    preds = [
        {"start": 0.0, "end": 400.0, "selected": True},
        {"start": 400.0, "end": 700.0, "selected": True},
    ]
    m = selection_metrics(preds)
    assert m["selected_duration_sec"] == 700.0
    assert m["budget_compliant"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_harness.py -k selection -v`
Expected: FAIL — `cannot import name 'selection_metrics'`.

- [ ] **Step 3: Write the implementation**

Add to `eval/harness.py`:

```python
def selection_metrics(preds, budget_sec=600.0):
    """Selection table (PRD §5). Reads the 'selected' flag.

    - selected_duration_sec: total length of selected rallies
    - budget_compliant: total <= budget (hard limit)
    - utilization: total / budget
    - rally_count: number of selected rallies
    - keep_rate: selected / all detected
    """
    selected = [p for p in preds if p.get("selected")]
    selected_dur = sum(p["end"] - p["start"] for p in selected)
    n_pred = len(preds)
    return {
        "selected_duration_sec": selected_dur,
        "budget_compliant": selected_dur <= budget_sec,
        "utilization": selected_dur / budget_sec if budget_sec else 0.0,
        "rally_count": len(selected),
        "keep_rate": len(selected) / n_pred if n_pred else 0.0,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_harness.py -k selection -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add eval/harness.py tests/test_harness.py
git commit -m "feat(eval): selection metrics (budget, utilization, count, keep rate)"
```

---

### Task 5: File I/O, CLI, and `make eval`

Wires the logic to real files: read a `rallies.json` and a label file, print both tables. Adds the `make eval` / `make test` shortcuts. This is the task that satisfies Phase 0's exit criterion — running the harness on a hand-written stub.

**Files:**
- Modify: `eval/harness.py`
- Modify: `tests/test_harness.py`
- Create: `Makefile`

**Interfaces:**
- Consumes: `detection_metrics`, `selection_metrics`.
- Produces:
  - `load_rallies(path) -> (source_duration_sec, rallies_list)`
  - `load_labels(path) -> labels_list`
  - `format_tables(det, sel) -> str`
  - `main(argv=None)` — parses `--pred` and `--labels`, prints the tables.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_harness.py` (top of file, with the other imports):

```python
import json
from eval.harness import main
```

Add the test:

```python
def test_main_prints_both_tables(tmp_path, capsys):
    pred_file = tmp_path / "rallies.json"
    pred_file.write_text(json.dumps({
        "source_duration_sec": 600.0,
        "rallies": [{"start": 0.0, "end": 10.0, "selected": True}],
    }))
    labels_file = tmp_path / "labels.jsonl"
    labels_file.write_text(
        json.dumps({"start": 0.0, "end": 10.0, "duration": 10.0, "rally_id": 1}) + "\n"
    )

    main(["--pred", str(pred_file), "--labels", str(labels_file)])

    out = capsys.readouterr().out
    assert "Detection" in out
    assert "Selection" in out
    assert "1.00" in out  # perfect recall on this stub
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_harness.py -k main -v`
Expected: FAIL — `cannot import name 'main'`.

- [ ] **Step 3: Write the implementation**

Add the import at the top of `eval/harness.py` (with the `import statistics` line):

```python
import argparse
import json
```

Add to `eval/harness.py`:

```python
def load_rallies(path):
    """Read a predictions file (rallies.json). Returns (source_duration_sec, rallies)."""
    with open(path) as f:
        data = json.load(f)
    return data["source_duration_sec"], data["rallies"]


def load_labels(path):
    """Read a ground-truth label file (one JSON object per line, from label.py)."""
    labels = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                labels.append(json.loads(line))
    return labels


def format_tables(det, sel):
    """Render the two PRD §5 tables as plain text."""
    return "\n".join([
        "Detection",
        f"  rally recall            {det['recall']:.2f}  ({det['n_matched']}/{det['n_labeled']})",
        f"  false positives /10min  {det['false_pos_per_10min']:.2f}",
        f"  boundary error (median) {det['boundary_error_median_sec']:.2f} s",
        "Selection",
        f"  budget compliant        {sel['budget_compliant']}"
        f"  ({sel['selected_duration_sec']:.1f}s / 600s)",
        f"  utilization             {sel['utilization']:.2f}",
        f"  rally count             {sel['rally_count']}",
        f"  keep rate               {sel['keep_rate']:.2f}",
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Score predicted rallies against labels (PRD §5)."
    )
    ap.add_argument("--pred", required=True, help="rallies.json (predictions)")
    ap.add_argument("--labels", required=True, help="label file, JSON-per-line (ground truth)")
    args = ap.parse_args(argv)

    source_dur, preds = load_rallies(args.pred)
    gts = load_labels(args.labels)
    det = detection_metrics(preds, gts, source_dur)
    sel = selection_metrics(preds)
    print(format_tables(det, sel))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_harness.py -k main -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Add the Makefile**

Create `Makefile` (recipes MUST be indented with a real TAB, not spaces):

```make
.PHONY: eval test

eval:
	python3 -m eval.harness --pred rallies.json --labels eval/labels/dev-set-B.jsonl

test:
	python3 -m pytest -q
```

- [ ] **Step 6: Run the whole suite**

Run: `python3 -m pytest -q`
Expected: PASS (all tests from Tasks 1-5 green).

- [ ] **Step 7: Commit**

```bash
git add eval/harness.py tests/test_harness.py Makefile
git commit -m "feat(eval): file I/O, CLI, and make eval/test targets"
```

---

## Notes for the implementer

- **Run everything from the repo root** so `python3 -m eval.harness` and `python3 -m pytest` resolve the `eval` package.
- **`python3`, not `python`** — plain `python` is absent on this machine.
- **Makefile tabs:** the two recipe lines under `eval:` and `test:` must start with a TAB character, or `make` errors with "missing separator."
- **What this slice does NOT do:** no detector, no video, no wall-clock metric, no dev/eval holdout enforcement. It scores whatever predictions + labels you hand it. Holdout separation stays a manual discipline for now (PRD §5 protocol).
