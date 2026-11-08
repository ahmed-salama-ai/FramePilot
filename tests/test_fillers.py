import pytest

from ai_director.audio.fillers import find_candidates, load_fillers, removed_in

CFG = load_fillers()


def row(speaker, *words, rid=0):
    """('word', start, end) ... -> one transcript row."""
    return {"id": rid, "speaker": speaker, "words": [{"w": w, "start": a, "end": b} for w, a, b in words]}


def flow(text, speaker="A", start=0.0, step=0.3, gap=0.0, rid=0):
    """A row of words said back to back (no pauses unless `gap`)."""
    words, t = [], start
    for w in text.split():
        words.append((w, round(t, 3), round(t + step, 3)))
        t += step + gap
    return row(speaker, *words, rid=rid)


def only(cands, text):
    found = [c for c in cands if c["text"] == text]
    assert len(found) == 1, found
    return found[0]


def test_the_list_file_loads_with_its_rule():
    assert CFG["rule"] == {"max_seconds": 0.5, "pause": 0.15, "phrase_start": True, "keep_questions": True}
    assert {e["id"] for e in CFG["hesitation"]} >= {"ah", "umm", "hmm", "aaa", "eeh"}


def test_isolated_short_yani_is_a_standard_filler():
    rows = [row("A", ("انا", 0.0, 0.3), ("يعني", 0.6, 0.8), ("مش", 1.1, 1.3), ("عارف", 1.3, 1.6))]
    c = only(find_candidates(rows, CFG), "يعني")
    assert c["decision"] == "standard" and c["gap_before"] == 0.3
    assert removed_in([c], "standard") == [c] and removed_in([c], "conservative") == [] and removed_in([c], "off") == []


def test_yani_inside_a_phrase_needs_no_pause_but_a_long_one_is_kept():
    inside = only(find_candidates([flow("انا مش يعني فاهم")], CFG), "يعني")
    assert inside["decision"] == "standard"                                  # no_pause_needed
    long_ = only(find_candidates([row("A", ("انا", 0, 0.3), ("يعني", 0.6, 1.4), ("كده", 1.4, 1.7))], CFG), "يعني")
    assert long_["decision"] == "kept" and long_["reason"] == "too long: said on purpose"


@pytest.mark.parametrize("word", ["مثلا", "بقى"])
def test_masalan_and_ba2a_need_no_pause_either(word):
    assert only(find_candidates([flow(f"هو عمل {word} الموضوع ده")], CFG), word)["decision"] == "standard"


def test_other_discourse_words_still_need_a_pause():
    c = only(find_candidates([flow("انا قلت طيب الموضوع ده")], CFG), "طيب")
    assert c["decision"] == "kept" and "no pause" in c["reason"]


def test_a_question_is_kept():
    rows = [row("A", ("جايين", 0, 0.3), ("بفلوسهم", 0.3, 0.8), ("يعني؟", 0.8, 1.0)), flow("اه", speaker="B", start=1.5, rid=1)]
    c = only(find_candidates(rows, CFG), "يعني؟")
    assert c["decision"] == "kept" and "question" in c["reason"]


def test_questions_can_be_treated_like_any_word():
    cfg = {**CFG, "rule": {**CFG["rule"], "keep_questions": False}}
    rows = [row("A", ("تفيدنا", 0, 0.4), ("ازاي", 0.4, 0.8), ("بقى؟", 0.8, 1.0)), flow("طبعا", speaker="B", start=1.6, rid=1)]
    assert only(find_candidates(rows, cfg), "بقى؟")["decision"] == "standard"
    assert only(find_candidates(rows, CFG), "بقى؟")["decision"] == "kept"


def test_a_phrase_start_counts_as_isolated():
    c = only(find_candidates([flow("طب انت عارف")], CFG), "طب")
    assert c["phrase_start"] and c["decision"] == "standard"


def test_tib_after_college_is_medicine_and_stays():
    c = only(find_candidates([flow("هو في كلية طب دلوقتي")], CFG), "طب")
    assert c["decision"] == "kept" and "كلية" in c["reason"]


def test_keda_only_at_the_end_of_a_phrase():
    mid = only(find_candidates([flow("عمل كده النهارده الصبح")], CFG), "كده")
    assert mid["decision"] == "kept" and "end of a phrase" in mid["reason"]
    end = only(find_candidates([flow("هو عمل كده")], CFG), "كده")
    assert end["decision"] == "standard"


def test_ah_as_a_reply_is_yes_and_stays():
    rows = [flow("انت جاي بكره", speaker="A", rid=0), flow("اه جاي", speaker="B", start=2.0, rid=1)]
    c = only(find_candidates(rows, CFG), "اه")
    assert c["turn_start"] and c["decision"] == "kept" and "yes" in c["reason"]


def test_ah_before_of_course_is_yes_and_stays():
    c = only(find_candidates([flow("هو قال اه طبعا")], CFG), "اه")
    assert c["decision"] == "kept"


def test_ah_hesitating_inside_a_turn_is_conservative():
    c = only(find_candidates([flow("هو قال اه الموضوع صعب")], CFG), "اه")
    assert c["decision"] == "conservative"
    assert removed_in([c], "conservative") == [c] and removed_in([c], "standard") == [c]


@pytest.mark.parametrize("word, entry", [("همم", "hmm"), ("هممم", "hmm"), ("امم", "umm"), ("ممم", "umm"),
                                         ("اييييه", "eeh"), ("ااا", "aaa"), ("أأأ", "aaa")])
def test_stretched_hesitation_sounds(word, entry):
    c = only(find_candidates([flow(f"هو {word} قال")], CFG), word)
    assert c["entry"] == entry and c["decision"] == "conservative"


@pytest.mark.parametrize("sentence", ["هم جايين بكره", "ام احمد جات", "انت قلت ايه"])
def test_plain_they_mother_and_what_are_never_hesitations(sentence):
    cands = find_candidates([flow(sentence)], CFG)
    assert all(c["decision"] == "kept" for c in cands)
    assert not removed_in(cands, "standard")


def test_two_word_phrases_win_over_one_word():
    c = only(find_candidates([flow("الموضوع اللي هو بالظبط", gap=0.2)], CFG), "اللي هو")
    assert c["entry"] == "elly-howa" and c["decision"] == "standard" and c["start"] == 0.5


def test_yani_eh_is_a_real_question_and_stays():
    c = only(find_candidates([flow("الموضوع يعني ايه بالظبط", gap=0.2)], CFG), "يعني ايه")
    assert c["entry"] == "yani-eh" and c["decision"] == "kept"


def test_yani_ending_a_sentence_adds_emphasis_and_stays():
    c = only(find_candidates([flow("ما فيش خريجين دول يعني.", gap=0.2), flow("ما طبعا", start=3.0, rid=1)], CFG),
             "يعني.")
    assert c["decision"] == "kept" and "ends the sentence" in c["reason"]


def test_keda_meaning_like_that_stays():
    c = only(find_candidates([flow("حاجه شبه كده.")], CFG), "كده.")
    assert c["decision"] == "kept" and "شبه" in c["reason"]


def test_english_like_as_a_verb_or_comparison_stays():
    for s in ("i like it", "it looks like rain", "do it like this"):
        assert not removed_in(find_candidates([flow(s)], CFG), "standard"), s
    c = only(find_candidates([row("A", ("it", 0, 0.2), ("was,", 0.2, 0.5), ("like,", 0.5, 0.7), ("great", 0.9, 1.2))],
                             CFG), "like,")
    assert c["decision"] == "standard"


def test_english_hesitation_and_openers():
    cands = find_candidates([flow("um so we start"), flow("we did so much", start=3.0, rid=1)], CFG)
    assert only(cands, "um")["decision"] == "conservative"
    so = [c for c in cands if c["text"] == "so"]
    assert [c["decision"] for c in so] == ["standard", "kept"]                 # only at the start of a phrase


def test_a_session_can_use_its_own_list(tmp_path):
    (tmp_path / "fillers.yaml").write_text("hesitation:\n  - {id: x, words: [بطيخ]}\n", encoding="utf-8")
    cfg = load_fillers(tmp_path)
    cands = find_candidates([flow("يعني بطيخ")], cfg)
    assert [c["text"] for c in cands] == ["بطيخ"]


def test_a_broken_list_is_rejected_clearly(tmp_path):
    (tmp_path / "fillers.yaml").write_text("discourse:\n  - {id: y, words: [يعني], only: {louder: true}}\n",
                                           encoding="utf-8")
    with pytest.raises(ValueError, match="unknown condition louder"):
        load_fillers(tmp_path)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="off, conservative, standard"):
        removed_in([], "aggressive")
