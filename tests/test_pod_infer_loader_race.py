"""The loader thread in scripts/pod_infer.py reads frames ahead of the main loop and, at the
end of the video, sets img1/img2/img3 to None while the main loop may still be writing the
last results. Reading img1.shape inside that loop crashed a real staging job near the end
of a 5-minute part (AttributeError: 'NoneType' object has no attribute 'shape'), after an
earlier run had passed by timing luck. Read as text, so it runs without TensorFlow."""
import pathlib

SOURCE = (pathlib.Path(__file__).resolve().parent.parent / "scripts" / "pod_infer.py").read_text()


def test_no_frame_variable_is_read_once_the_loader_thread_is_running():
    started = SOURCE.index("producer = threading.Thread")
    after = SOURCE[started:]
    for name in ("img1", "img2", "img3"):
        assert f"{name}." not in after and f"{name}[" not in after, (
            f"{name} is the loader thread's variable and is None at the end of the video; "
            "take what you need from it before the thread starts (see frame_shape)")


def test_the_frame_size_is_taken_before_the_loader_thread_starts():
    assert SOURCE.index("frame_shape = img1.shape") < SOURCE.index("producer = threading.Thread")
