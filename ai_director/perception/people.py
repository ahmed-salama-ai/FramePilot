# ai_director/perception/people.py — how many people, and how much they move (YOLO11 + ByteTrack)
# Owner: Sara Walid (taken over by Ahmed Salama)


def people(yolo, frame, prev_centers):
    """One frame -> {"num_people", "gesture_score"}. prev_centers remembers where each tracked person was."""
    r = yolo.track(frame, persist=True, classes=[0], conf=0.4, verbose=False, tracker="bytetrack.yaml")[0]
    h, w = frame.shape[:2]
    moves = []
    if r.boxes.id is not None:
        for (x1, y1, x2, y2), tid in zip(r.boxes.xyxy.tolist(), r.boxes.id.int().tolist()):
            c = ((x1 + x2) / 2 / w, (y1 + y2) / 2 / h)                # box centre, 0..1 of the image
            if tid in prev_centers:                                   # how far this person moved since 0.1 s ago
                moves.append(abs(c[0] - prev_centers[tid][0]) + abs(c[1] - prev_centers[tid][1]))
            prev_centers[tid] = c
    gesture = min(max(moves, default=0) / 0.05, 1.0)                  # moved 5% of the image in 0.1 s = 1
    return {"num_people": len(r.boxes), "gesture_score": round(gesture, 3)}
