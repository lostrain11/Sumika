"""One authorized camera frame in the isolated desktop runtime; no retained file."""
import base64
import json
from extensions.desktop.perception import read_camera_frame


def collect_frame():
    import cv2
    bitmap = read_camera_frame(approved=True)
    height, width = bitmap.shape[:2]
    scale = min(1, 1024 / max(height, width))
    if scale < 1:
        bitmap = cv2.resize(bitmap, (max(1, round(width * scale)), max(1, round(height * scale))))
    ok, encoded = cv2.imencode('.jpg', bitmap, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok or len(encoded) > 400_000:
        raise RuntimeError('camera frame exceeds image budget')
    return {'media_type': 'image/jpeg',
            'data_base64': base64.b64encode(encoded.tobytes()).decode('ascii')}


if __name__ == '__main__':
    print(json.dumps(collect_frame()))
