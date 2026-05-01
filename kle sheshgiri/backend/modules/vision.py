import cv2
import numpy as np


def check_image_quality(image: np.ndarray) -> dict:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))

    h, w = gray.shape[:2]
    aspect = w / max(h, 1)
    distorted = aspect < 0.5 or aspect > 2.5

    is_blurry = blur_score < 80.0
    is_low_quality = brightness < 45.0 or brightness > 220.0 or contrast < 25.0

    return {
        "blur_score": blur_score,
        "brightness": brightness,
        "contrast": contrast,
        "is_blurry": is_blurry,
        "is_low_quality": is_low_quality,
        "is_distorted": distorted,
    }
