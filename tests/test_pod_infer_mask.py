"""pod_infer's faster court mask (2026-10-27) must give the exact pixels the old
`img * mask` did: the ball model was tuned on those inputs."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("tensorflow")   # pod_infer imports it; the pod image has it
from scripts import pod_infer  # noqa: E402


def test_bitwise_and_mask_equals_the_old_multiply():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (108, 192, 3), dtype=np.uint8)
    mask = (rng.random((108, 192)) > 0.4).astype(np.uint8)
    mask3 = cv2.merge([mask * 255] * 3)
    assert np.array_equal(pod_infer.apply_mask(img, mask3), img * mask[:, :, None])
