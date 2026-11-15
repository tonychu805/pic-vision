# TrackNet in PyTorch (src/tracknet_torch.py, 2026-11-12). The real check is
# against the Keras model on real footage (EXPERIMENTS 2026-11-12: heatmaps
# within 8e-4, every detection the same); these pin the pieces that check
# relies on, each beside its "and not otherwise" pair.
import json
import os

import numpy as np
import pytest
import torch

from src import tracknet_torch as T

os.environ.setdefault("JOB_ID", "test-job-id")
os.environ.setdefault("JOB_TOKEN", "test-token")
os.environ.setdefault("BUCKET", "test-bucket")
os.environ.setdefault("OUTPUT_BUCKET", "test-output-bucket")
os.environ.setdefault("BRAND_ID", "test-brand-id")


def test_column_norm_is_keras_batch_norm_over_the_last_axis():
    x = torch.randn(2, 4, 3, 5)
    n = T.ColumnNorm(5, 1e-3)
    g, b, m, v = (torch.rand(5) + 0.5 for _ in range(4))
    with torch.no_grad():
        n.weight.copy_(g); n.bias.copy_(b); n.running_mean.copy_(m); n.running_var.copy_(v)
    want = (x - m) / torch.sqrt(v + 1e-3) * g + b           # broadcast over the last (width) axis
    assert torch.allclose(n(x), want, atol=1e-6)
    # Paired: a per-channel norm (what BatchNorm2d would do) gives something else.
    per_channel = torch.nn.BatchNorm2d(4, eps=1e-3).eval()
    assert not torch.allclose(per_channel(x), want, atol=1e-3)


SPEC = {"input": [9, 8, 16], "layers": [
    {"name": "in", "type": "InputLayer", "inputs": ["in"]},
    {"name": "c1", "type": "Conv2D", "inputs": ["in"], "filters": 4, "kernel": [3, 3], "strides": [1, 1],
     "padding": "same", "activation": "linear", "use_bias": True},
    {"name": "a1", "type": "Activation", "inputs": ["c1"], "activation": "relu"},
    {"name": "b1", "type": "BatchNormalization", "inputs": ["a1"], "epsilon": 1e-3, "axis": [3]},
    {"name": "p1", "type": "MaxPooling2D", "inputs": ["b1"], "pool": [2, 2], "strides": [2, 2], "padding": "valid"},
    {"name": "u1", "type": "UpSampling2D", "inputs": ["p1"], "size": [2, 2], "interpolation": "nearest"},
    {"name": "cat", "type": "Concatenate", "inputs": ["u1", "b1"], "axis": 1},
    {"name": "c2", "type": "Conv2D", "inputs": ["cat"], "filters": 3, "kernel": [1, 1], "strides": [1, 1],
     "padding": "same", "activation": "linear", "use_bias": True},
    {"name": "out", "type": "Activation", "inputs": ["c2"], "activation": "sigmoid"},
]}


def test_a_spec_builds_and_round_trips_through_the_pt_file(tmp_path):
    m = T.TrackNet(SPEC).eval()
    x = torch.rand(2, 9, 8, 16)
    with torch.no_grad():
        y = m(x)
    assert y.shape == (2, 3, 8, 16) and float(y.min()) >= 0 and float(y.max()) <= 1
    path = tmp_path / "m.pt"
    torch.save({"spec": SPEC, "state_dict": m.state_dict()}, path)
    again = T.load(str(path), device="cpu")
    with torch.no_grad():
        assert torch.equal(again(x), y)


def test_an_unsupported_layer_is_refused_not_guessed():
    bad = json.loads(json.dumps(SPEC))
    bad["layers"][3]["axis"] = [1]                 # per-channel batch norm: not what the Keras model does
    with pytest.raises(ValueError):
        T.TrackNet(bad)
    bad = json.loads(json.dumps(SPEC))
    bad["layers"][1]["padding"] = "valid"
    with pytest.raises(ValueError):
        T.TrackNet(bad)


def test_pod_infer_runs_a_pt_model_with_torch(tmp_path, monkeypatch):
    from scripts import pod_infer
    path = tmp_path / "m.pt"
    torch.save({"spec": SPEC, "state_dict": T.TrackNet(SPEC).state_dict()}, path)
    monkeypatch.setattr(pod_infer, "_tf_infer", lambda *a: pytest.fail("TensorFlow path used for a .pt model"))
    infer = pod_infer.load_infer(str(path))
    y = infer(np.random.rand(1, 9, 8, 16).astype(np.float32))
    assert isinstance(y, np.ndarray) and y.dtype == np.float32 and y.shape == (1, 3, 8, 16)


def test_pod_infer_keeps_tensorflow_for_a_saved_model(monkeypatch):
    from scripts import pod_infer
    seen = []
    monkeypatch.setattr(pod_infer, "_tf_infer", lambda path, half: seen.append((path, half)) or "tf infer")
    assert pod_infer.load_infer("/workspace/weights_k14_epoch19") == "tf infer"
    assert seen == [("/workspace/weights_k14_epoch19", True)]


class FakeS3:
    def __init__(self):
        self.calls = []

    def download_file(self, bucket, key, dest):
        self.calls.append((bucket, key, dest))
        open(dest, "wb").write(b"x")


def test_a_pt_model_is_downloaded_as_is(monkeypatch, tmp_path):
    from cloud_pipeline import pod_driver
    monkeypatch.setattr(pod_driver, "WEIGHTS_R2_KEY", "weights/m.pt")
    monkeypatch.setattr(pod_driver, "WEIGHTS_LOCAL", str(tmp_path / "m.pt"))
    monkeypatch.setattr(pod_driver.subprocess, "run", lambda *a, **k: pytest.fail("a .pt model must not be untarred"))
    s3 = FakeS3()
    pod_driver.fetch_weights(s3, str(tmp_path))
    assert os.path.exists(tmp_path / "m.pt") and s3.calls[0][1] == "weights/m.pt"
    pod_driver.fetch_weights(s3, str(tmp_path))
    assert len(s3.calls) == 1                     # once per pod


def test_a_tar_model_is_still_extracted(monkeypatch, tmp_path):
    from cloud_pipeline import pod_driver
    monkeypatch.setattr(pod_driver, "WEIGHTS_R2_KEY", "weights/old.tar")
    monkeypatch.setattr(pod_driver, "WEIGHTS_LOCAL", str(tmp_path / "old_model_dir"))
    ran = []
    monkeypatch.setattr(pod_driver.subprocess, "run", lambda cmd, **k: ran.append(cmd))
    pod_driver.fetch_weights(FakeS3(), str(tmp_path))
    assert ran and ran[0][:2] == ["tar", "-xf"]


def test_threads_follow_the_override_and_never_the_host_count(monkeypatch):
    from scripts import pod_infer
    import cv2
    monkeypatch.setenv("PIC_VISION_INFER_THREADS", "3")
    info = pod_infer.limit_threads()
    assert info["cv2_threads"] == 3 and cv2.getNumThreads() == 3
    assert info["torch_threads"] <= 2              # torch only copies on the CPU here
    # Paired: without the override it is the usable count, which can be below the host's.
    monkeypatch.delenv("PIC_VISION_INFER_THREADS")
    info = pod_infer.limit_threads()
    assert info["cv2_threads"] == pod_infer.usable_cpus() <= info["host_cpus"]


def test_a_cpu_model_runs_eagerly_with_no_graph(tmp_path, monkeypatch):
    from scripts import pod_infer
    path = tmp_path / "m.pt"
    torch.save({"spec": SPEC, "state_dict": T.TrackNet(SPEC).state_dict()}, path)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(pod_infer, "_cuda_graph", lambda *a: pytest.fail("no CUDA graph on the CPU"))
    y = pod_infer.load_infer(str(path))(np.random.rand(1, 9, 8, 16).astype(np.float32))
    assert y.shape == (1, 3, 8, 16)


def test_the_pod_keeps_inferences_timing_line(monkeypatch):
    import sys
    from cloud_pipeline import pod_driver
    monkeypatch.setattr(pod_driver, "patch_job", lambda **k: False)
    got = pod_driver._run_inference_streaming([sys.executable, "-c", 'print("  300/900  50 fps  ETA 0.2 min"); print(\'TIMING {"fps": 50.0, "wait_s": 1.5}\')'])
    assert got == {"fps": 50.0, "wait_s": 1.5}
    # Paired: an older pod_infer with no timing line still runs, just reports none.
    assert pod_driver._run_inference_streaming([sys.executable, "-c", 'print("Done")']) is None
