class Switcher:
    def __init__(self, cfg, start_cam):
        self.c, self.cur, self.shot_start = cfg, start_cam, 0.0
        self.cand, self.cand_since = None, None
        self.last_speaker, self.pending = None, None
        self.talk_t = None                       # the last time somebody was talking (reaction shots)

    def step(self, t, scores, speaker_cam=None, faces=None):
        """scores = {cam: score} at time t; faces = the cameras showing a face (None = unknown: every camera).
        Returns the camera on air."""
        c = self.c
        if speaker_cam is not None and speaker_cam != self.last_speaker:
            self.last_speaker, self.pending = speaker_cam, speaker_cam   # a new person started talking
        if speaker_cam is not None:
            self.talk_t = t
        dur = round(t - self.shot_start, 3)      # round: in a computer 2.4 - 2.0 = 0.3999999999999999
        if dur < c["min_shot"]:
            return self.cur                                           # rule 1: never cut too early
        if self.pending is not None:
            cam, self.pending = self.pending, None
            if cam != self.cur:
                return self._cut(t, cam)                              # rule 2: follow the new speaker
        if dur > c["max_shot"]:                                       # rule 3: variety
            listener = self._listener(t, scores, speaker_cam, faces)
            if listener is not None:                                  # rule 3b: a reaction shot of a listener,
                self.pending = self.cur                               # then back to the speaker after min_shot
                return self._cut(t, listener)
            others = {k: v for k, v in scores.items() if k != self.cur}
            nxt = c["wide_cam"] if self.cur != c["wide_cam"] else max(others, key=others.get)
            return self._cut(t, nxt)
        best = max(scores, key=scores.get)
        all_low = scores[best] < c["low_score"]
        if all_low:
            best = c["wide_cam"]                                      # rule 4: nothing good -> wide
        clearly_better = scores[best] > scores[self.cur] * (1 + c["margin"])
        if best != self.cur and (clearly_better or all_low):
            if self.cand != best:
                self.cand, self.cand_since = best, t
            elif round(t - self.cand_since, 3) >= c["hold"]:
                return self._cut(t, best)                             # rule 5: clear, stable winner
        else:
            self.cand = None
        return self.cur

    def _listener(self, t, scores, speaker_cam, faces):
        """Reaction shots (switcher.reactions, off by default): while the person on air keeps talking, the best other
        close-up that shows a face. A breath of at most switcher.reaction_pause s still counts as talking.
        None = no reaction shot (the wide shot, as before)."""
        c = self.c
        if not c.get("reactions"):
            return None
        if speaker_cam is None and self.talk_t is not None and t - self.talk_t <= c.get("reaction_pause", 0.0):
            speaker_cam = self.last_speaker                           # a short breath: the same person goes on
        if speaker_cam is None or self.cur != speaker_cam:
            return None
        close = {k: v for k, v in scores.items() if k not in (self.cur, c["wide_cam"]) and (faces is None or k in faces)}
        return max(close, key=close.get) if close else None

    def _cut(self, t, cam):
        self.cur, self.shot_start, self.cand = cam, t, None
        return cam