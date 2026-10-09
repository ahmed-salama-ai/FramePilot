# ai_director/perception/people.py — how many people, and how much they move their hands (YOLO11-pose + ByteTrack)
# Owner: Sara Walid (taken over by Ahmed Salama; 2026-10-08: pose instead of boxes. The box centre mostly measured people
# shifting in their seats; the wrists show real gestures. Tested on s01-s03: helps the panel (s03), see CLAUDE.md.
# 2026-10-09: also returns every tracked person, so faces.py can cut out their heads)
WRISTS = (9, 10)                 # COCO body points: left and right wrist
FULL = 0.15                      # a wrist moving 0.15 of the person's height in 0.1 s = gesture 1


def people(pose, frame, prev):
    """One frame -> ({"num_people", "gesture_score"}, persons). gesture = the biggest wrist movement since 0.1 s ago,
    measured from the person's own box centre and in their own height (so walking or sitting near the camera doesn't
    count). persons = [(track id, box, 17 body points, their confidences)] in this frame's pixels.
    prev remembers every tracked person: {track id: (box centre x, y, height, {wrist: (x, y)})}."""
    r = pose.track(frame, persist=True, conf=0.4, verbose=False, tracker="bytetrack.yaml")[0]
    move, persons = 0.0, []
    if r.boxes.id is not None and r.keypoints is not None:
        persons = list(zip(r.boxes.id.int().tolist(), r.boxes.xyxy.tolist(), r.keypoints.xy.tolist(),
                           r.keypoints.conf.tolist()))
        for tid, (x1, y1, x2, y2), pts, cf in persons:
            h, cx, cy = max(y2 - y1, 1.0), (x1 + x2) / 2, (y1 + y2) / 2
            wr = {j: ((pts[j][0] - cx) / h, (pts[j][1] - cy) / h) for j in WRISTS if cf[j] > 0.5}
            if tid in prev:
                old = prev[tid][3]
                move = max([move] + [abs(x - old[j][0]) + abs(y - old[j][1]) for j, (x, y) in wr.items() if j in old])
            prev[tid] = (cx, cy, h, wr)
    return {"num_people": len(r.boxes), "gesture_score": round(min(move / FULL, 1.0), 3)}, persons
