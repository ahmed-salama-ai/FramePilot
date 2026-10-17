import cv2
import numpy as np


def grid_at(caps: dict, t: float, out_path, cell=(336, 189)) -> str:
    """caps = {cam_id: cv2.VideoCapture} (open them once, reuse them). Max 4 cameras; missing tiles are black."""
    tiles = []
    for cam, cap in list(caps.items())[:4]:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)                      #jump to time t
        ok, f = cap.read()
        f = cv2.resize(f, cell) if ok else np.zeros((cell[1], cell[0], 3), np.uint8)
        cv2.putText(f, f"CAM {cam}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        tiles.append(f)
    while len(tiles) < 4:
        tiles.append(np.zeros_like(tiles[0]))
    canvas = np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])  #672 x 378
    cv2.imwrite(str(out_path), canvas)
    return str(out_path)
