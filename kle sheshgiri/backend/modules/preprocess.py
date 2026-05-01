import cv2
import numpy as np


MAX_SIDE = 1280


def decode_and_preprocess(image_bytes: bytes) -> tuple[np.ndarray, dict]:
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Unable to decode image")

    height, width = image.shape[:2]
    scale = min(1.0, MAX_SIDE / max(height, width))
    if scale < 1.0:
        image = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)

    # Normalize brightness while preserving detail using YCrCb equalization.
    ycrcb = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
    ycrcb[:, :, 0] = cv2.equalizeHist(ycrcb[:, :, 0])
    normalized = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)

    metadata = {
        "original_width": width,
        "original_height": height,
        "processed_width": normalized.shape[1],
        "processed_height": normalized.shape[0],
    }
    return normalized, metadata
