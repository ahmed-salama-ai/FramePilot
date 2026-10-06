# ai_director/perception/quality.py — is the picture sharp, well lit and still?
# Owner: Sara Walid (taken over by Ahmed Salama)
import cv2
import numpy as np


def quality(gray, prev_gray):
    """One grey frame (+ the one 0.1 s before) -> {"sharpness", "exposure_ok", "shake"}, all 0..1."""
    sharp = min(cv2.Laplacian(gray, cv2.CV_64F).var() / 300.0, 1.0)     # edges: blurry image -> small number
    mean, clipped = gray.mean(), ((gray < 5) | (gray > 250)).mean()     # brightness, share of black/white pixels
    exposure_ok = 1.0 if 60 < mean < 190 and clipped < 0.05 else 0.4
    shake = 0.0
    if prev_gray is not None:                                           # how far the whole image moved
        (dx, dy), _ = cv2.phaseCorrelate(np.float32(prev_gray), np.float32(gray))
        shake = min((dx * dx + dy * dy) ** 0.5 / 8.0, 1.0)              # an 8-pixel jump = very shaky
    return {"sharpness": round(float(sharp), 4), "exposure_ok": exposure_ok, "shake": round(float(shake), 4)}
