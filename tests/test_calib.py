import numpy as np
import pytest
import src.calib as calib_mod
from src.calib import detect_net_y


def _make_frame_with_line(h, w, line_y, color=200):
    """Gray frame with a horizontal white line at line_y."""
    f = np.zeros((h, w), dtype=np.uint8)
    f[line_y - 1:line_y + 2, :] = color
    return f


class FakeCap:
    """Minimal cv2.VideoCapture stub returning frames with a net line."""

    def __init__(self, frames):
        self._frames = frames
        self._idx = 0
        self.h, self.w = frames[0].shape[:2]

    def get(self, prop):
        import cv2
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return float(len(self._frames))
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.h)
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self.w)
        return 0.0

    def set(self, prop, val):
        self._idx = int(val)

    def read(self):
        if self._idx >= len(self._frames):
            return False, None
        frame = self._frames[self._idx]
        # calib converts BGR to gray; return 3-channel frame
        bgr = np.stack([frame, frame, frame], axis=-1)
        self._idx += 1
        return True, bgr

    def release(self):
        pass


def test_detect_net_y_finds_horizontal_line(monkeypatch):
    h, w = 600, 800
    net_y = 300  # exactly middle
    # 100 frames so 20% window = 20 frames ≥ 3 minimum
    frames = [_make_frame_with_line(h, w, net_y) for _ in range(100)]
    cap = FakeCap(frames)
    monkeypatch.setattr(calib_mod.cv2, "VideoCapture", lambda _: cap)

    result = detect_net_y("fake.mp4", n_frames=20)
    assert abs(result - net_y) < 15, f"expected ~{net_y}, got {result:.1f}"


def test_detect_net_y_raises_on_no_frames(monkeypatch):
    class EmptyCap:
        def get(self, p):
            import cv2
            return {cv2.CAP_PROP_FRAME_COUNT: 5.0,
                    cv2.CAP_PROP_FRAME_HEIGHT: 100.0,
                    cv2.CAP_PROP_FRAME_WIDTH: 200.0}.get(p, 0.0)
        def set(self, p, v): pass
        def read(self): return False, None
        def release(self): pass

    monkeypatch.setattr(calib_mod.cv2, "VideoCapture", lambda _: EmptyCap())
    with pytest.raises(RuntimeError, match="Too few"):
        detect_net_y("empty.mp4")
