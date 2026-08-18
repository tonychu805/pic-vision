import json

from label_web import labels_path_for, discover_videos, resolve_selection


def test_labels_path_follows_the_project_convention():
    # videos/brickwall_30fps.mp4 -> eval/labels/brickwall_30fps.jsonl
    assert labels_path_for("videos/brickwall_30fps.mp4", "eval/labels") == \
        "eval/labels/brickwall_30fps.jsonl"
    assert labels_path_for("/abs/path/IMG_7744_fixed.mp4", "eval/labels") == \
        "eval/labels/IMG_7744_fixed.jsonl"


def _mkvideo(d, name, size=10):
    p = d / name
    p.write_bytes(b"\0" * size)
    return p


def test_discover_lists_playable_videos_with_their_label_counts(tmp_path):
    vids, labels = tmp_path / "videos", tmp_path / "labels"
    vids.mkdir(); labels.mkdir()
    _mkvideo(vids, "alpha.mp4")
    _mkvideo(vids, "beta.mp4")
    (labels / "alpha.jsonl").write_text(
        json.dumps({"start": 1.0, "end": 2.0, "duration": 1.0}) + "\n")

    found = discover_videos(str(vids), str(labels))
    by_name = {v["name"]: v for v in found}
    assert set(by_name) == {"alpha.mp4", "beta.mp4"}
    assert by_name["alpha.mp4"]["n_labels"] == 1      # existing labels are counted
    assert by_name["beta.mp4"]["n_labels"] == 0       # no label file yet -> 0, not an error


def test_discover_skips_unplayable_files_and_subdirectories(tmp_path):
    # .MOV/HEVC does not decode in the browser (module docstring); raw/ holds
    # exactly those, so a recursive scan would offer files that cannot be labelled.
    vids, labels = tmp_path / "videos", tmp_path / "labels"
    (vids / "raw").mkdir(parents=True); labels.mkdir()
    _mkvideo(vids, "good.mp4")
    _mkvideo(vids, "camera.MOV")
    _mkvideo(vids, "notes.txt")
    _mkvideo(vids / "raw", "buried.mp4")

    names = {v["name"] for v in discover_videos(str(vids), str(labels))}
    assert names == {"good.mp4"}


def test_discover_is_sorted_and_survives_a_missing_directory(tmp_path):
    vids, labels = tmp_path / "videos", tmp_path / "labels"
    vids.mkdir()
    for n in ("zeta.mp4", "alpha.mp4", "mid.mp4"):
        _mkvideo(vids, n)
    assert [v["name"] for v in discover_videos(str(vids), str(labels))] == \
        ["alpha.mp4", "mid.mp4", "zeta.mp4"]
    assert discover_videos(str(tmp_path / "nope"), str(labels)) == []


def test_resolve_selection_rejects_anything_not_discovered(tmp_path):
    # the picker passes a name from the browser straight back to the server, so
    # this is the path-traversal guard: only an exact discovered name resolves.
    vids, labels = tmp_path / "videos", tmp_path / "labels"
    vids.mkdir(); labels.mkdir()
    _mkvideo(vids, "good.mp4")
    found = discover_videos(str(vids), str(labels))

    assert resolve_selection("good.mp4", found)["name"] == "good.mp4"
    assert resolve_selection("../../etc/passwd", found) is None
    assert resolve_selection("/etc/passwd", found) is None
    assert resolve_selection("nope.mp4", found) is None
    assert resolve_selection("", found) is None
