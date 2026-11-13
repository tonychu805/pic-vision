"""The contact sheet Jev judges a rally from (scripts/eval_jev_rally.py's sheet(), validated 2026-10-17, PIC-226):
6 frames evenly spaced over the rally, 2 wide x 3 high in time order, numbered 1-6. Keep it identical to that sheet,
because Jev's accuracy was measured on exactly this input."""
import cv2
import numpy as np

TW, TH = 784, 441


def contact_sheet(video_path, start_sec, end_sec):
    """JPEG bytes (1568 x 1323) of the rally between start_sec and end_sec."""
    cap = cv2.VideoCapture(video_path)
    try:
        canvas = np.zeros((3 * TH, 2 * TW, 3), np.uint8)
        for i in range(6):
            cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * (start_sec + (i + 0.5) / 6 * (end_sec - start_sec)))
            ok, im = cap.read()
            if not ok:
                raise RuntimeError(f"could not decode frame {i + 1} of {video_path}")
            t = cv2.resize(im, (TW, TH))
            cv2.putText(t, str(i + 1), (12, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
            canvas[(i // 2) * TH:(i // 2 + 1) * TH, (i % 2) * TW:(i % 2 + 1) * TW] = t
    finally:
        cap.release()
    ok, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return buf.tobytes()
