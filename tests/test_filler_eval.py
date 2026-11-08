from ai_director.audio.fillers import find_candidates, load_fillers
from eval.filler_eval import score, truth

CFG = load_fillers()


def row(*words, rid=0, speaker="A"):
    return {"id": rid, "speaker": speaker, "words": [{"w": w, "start": a, "end": b} for w, a, b in words]}


ROWS = [row(("طب", 0.0, 0.2), ("انت", 0.2, 0.5), ("عارف", 0.5, 0.8), ("يعني", 1.2, 1.4), ("الموضوع", 1.6, 2.0),
            ("صعب", 2.0, 2.3), ("مثلا", 2.8, 3.1), ("هنا", 3.1, 3.4))]


def test_precision_counts_only_checked_removals_and_recall_counts_every_labelled_filler():
    cands = find_candidates(ROWS, CFG)
    assert [c["text"] for c in cands if c["decision"] == "standard"] == ["طب", "يعني", "مثلا"]
    fillers, not_fillers = {0, 3}, {6}                   # طب and يعني are fillers, مثلا is not
    r = score(cands, fillers, not_fillers, missed=[5.0], mode="standard")
    assert (r["removed"], r["tp"], r["fp"]) == (3, 2, 1)
    assert r["precision"] == 2 / 3 and r["recall_written"] == 1.0 and r["recall_all"] == 2 / 3
    off = score(cands, fillers, not_fillers, missed=[], mode="conservative")
    assert off["removed"] == 0 and off["precision"] is None


def test_unchecked_candidates_do_not_count_as_mistakes():
    cands = find_candidates(ROWS, CFG)
    r = score(cands, {0}, set(), missed=[], mode="standard")
    assert (r["tp"], r["fp"], r["unchecked"]) == (1, 0, 2) and r["precision"] == 1.0
    assert truth(cands[1], {0}, set()) is None
