# The court mask + crop + resize on the GPU (scripts/pod_infer.py gpu_prep,
# 2026-11-13) must hand the ball model what the CPU path (apply_mask + prep3)
# does. cv2's uint8 resize uses fixed-point weights, so the two can differ by
# one grey level; on a real 1080p frame 98% of values were identical.
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
torch = pytest.importorskip("torch")
from scripts import pod_infer  # noqa: E402

cuda = pytest.mark.skipif(not torch.cuda.is_available(), reason="needs CUDA")


def _frames(seed=0):
    """Three 1080p BGR frames: smooth gradients plus noise, like footage, not pure noise."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:1080, 0:1920]
    out = []
    for i in range(3):
        base = np.stack([(xx * (0.1 + i * 0.03)) % 256, (yy * 0.2) % 256, (xx + yy) * 0.06 % 256], -1)
        out.append(np.clip(base + rng.normal(0, 12, base.shape), 0, 255).astype(np.uint8))
    return out


def _cpu(trio, mask, crop):
    if mask is not None:
        mask3 = cv2.merge([mask * 255] * 3)
        trio = [pod_infer.apply_mask(im, mask3) for im in trio]
    return pod_infer.prep3(trio, crop)


@cuda
@pytest.mark.parametrize("masked", [False, True])
@pytest.mark.parametrize("crop", [None, (126, 0, 1920, 1009)])
def test_gpu_prep_matches_the_cpu_path(masked, crop):
    trio = _frames()
    mask = None
    if masked:
        mask = np.zeros((1080, 1920), np.uint8)
        mask[200:1000, 300:1700] = 1
    stage, prep = pod_infer.gpu_prep(mask, crop, trio[0].shape)
    got = prep(stage(trio))
    assert got.is_cuda and got.dtype == torch.float32 and tuple(got.shape) == (1, 9, 288, 512)
    want = _cpu(trio, mask, crop)
    levels = np.abs(got.cpu().numpy() - want) * 255
    assert levels.max() <= 1.0 + 1e-3              # never more than one grey level apart
    assert (levels < 1e-3).mean() > 0.85           # and mostly identical (89% on these noisy frames)
    # Paired: the same comparison catches a wrong channel order, a missed mask or a missed crop.
    assert np.abs(got.cpu().numpy()[:, [2, 1, 0, 5, 4, 3, 8, 7, 6]] - want).max() * 255 > 10
    if masked:
        assert np.abs(_cpu(trio, None, crop) - want).max() * 255 > 10
    if crop:
        assert np.abs(_cpu(trio, mask, None) - want).max() * 255 > 10


@cuda
def test_gpu_prep_matches_cv2_at_other_resolutions():
    rng = np.random.default_rng(1)
    for h, w in ((720, 1280), (640, 1280), (288, 512), (2160, 3840)):
        trio = [rng.integers(0, 256, (h, w, 3), dtype=np.uint8) for _ in range(3)]
        stage, prep = pod_infer.gpu_prep(None, None, trio[0].shape)
        assert np.abs(prep(stage(trio)).cpu().numpy() - _cpu(trio, None, None)).max() * 255 <= 1.0 + 1e-3


def test_the_cpu_path_is_kept_when_asked_or_without_a_torch_model(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert pod_infer.wants_gpu_prep("/workspace/tracknet_k14.pt")
    monkeypatch.setenv("PIC_VISION_INFER_GPU_PREP", "0")
    assert not pod_infer.wants_gpu_prep("/workspace/tracknet_k14.pt")
    monkeypatch.delenv("PIC_VISION_INFER_GPU_PREP")
    assert not pod_infer.wants_gpu_prep("/workspace/weights_k14_epoch19")     # TensorFlow
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert not pod_infer.wants_gpu_prep("/workspace/tracknet_k14.pt")
