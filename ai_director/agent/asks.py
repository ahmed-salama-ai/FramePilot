import re
from typing import Literal

from pydantic import BaseModel, Field

ARABIC, LATIN = re.compile("[؀-ۿ]"), re.compile("[A-Za-z]")
CJK = re.compile("[぀-ヿ㐀-鿿가-힯＀-￯]")
FRANCO = re.compile(r"\b[a-z]+[2357][a-z]+|\b[2357](?!nd\b|rd\b|th\b|st\b|min|sec)[a-z]{2,}", re.I)
LENGTH_WORD = re.compile(r"minute|\bmins?\b|second|\bsecs?\b|\d\s*s\b|دقيق|دقايق|دقائق|ثاني|ثواني|ثوان|de2i2|da2aye2|"
                         r"sanya|sawany", re.I)
CAPTION = re.compile(r"caption|subtitle|\bsubs?\b|ترجم|كابشن|سب ?تايتل|targam", re.I)
NAMES = {"ar": "Egyptian Arabic", "en": "English"}

WORDS = [
    (r"\b(?:a|one)?\s*minute and a half|\bone and a half minutes?", "90 sec"),
    (r"\bhalf (?:a )?minute", "30 sec"),
    (r"\b(?:a|an|one) minute", "1 min"),
    (r"\b([وبل]?)دقيقتين (?:و ?نص|و ?نصف)", r"\g<1>150 sec"),
    (r"\b([وبل]?)دقيق[ةه] (?:و ?نص|و ?نصف)", r"\g<1>90 sec"),
    (r"\b([وبل]?)(?:نص|نصف) دقيق[ةه]", r"\g<1>30 sec"),
    (r"\b([وبل]?)دقيقت(?:ين|ان)", r"\g<1>2 min"),
    (r"(?<!\d)(?<!\d )\b([وبل]?)دقيق[ةه](?!\s*\d)", r"\g<1>1 min"),
    (r"\bde2i2a w ?nos", "90 sec"), (r"\bnos de2i2a", "30 sec"), (r"\bde2i2t[ae]+[iy]?n", "2 min"),
    (r"(?<!\d)(?<!\d )\bde2i2a", "1 min"),
]
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30,
           "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
           "اتنين": 2, "اثنين": 2, "تلات": 3, "تلاتة": 3, "تلاته": 3, "ثلاث": 3, "ثلاثة": 3, "اربع": 4, "أربع": 4,
           "اربعة": 4, "أربعة": 4, "خمس": 5, "خمسة": 5, "خمسه": 5, "عشر": 10, "عشرة": 10, "عشرين": 20,
           "تلاتين": 30, "ثلاثين": 30, "اربعين": 40, "أربعين": 40, "خمسين": 50, "ستين": 60, "تسعين": 90}
UNIT = r"(minutes?|mins?|seconds?|secs?|s|دقيق[ةه]|دقايق|دقائق|ثاني[ةه]|ثواني|ثوان|da2aye2|sanya|sawany)"
MINUTES = r"(?:minutes?|mins?|دقيق[ةه]|دقايق|دقائق|da2aye2)"
NUM = r"(?<![\d:.])(\d+(?:\.\d+)?)"
SEP = r"\s*(?:-|–|—|to|or|and|ل|لـ|او|أو|الى|إلى|lel|le|aw)\s*"
LENGTH = re.compile(rf"{NUM}(?:\s*{UNIT})?(?:{SEP}{NUM})?\s*-?\s*{UNIT}(?!\w)")
CLOCK = re.compile(rf"(?<![\d:.])(\d{{1,2}})[:.]([0-5]\d)\s*-?\s*{MINUTES}(?!\w)")
PLUS = re.compile(rf"{NUM}\s*{MINUTES}\s*(?:,|and|و)?\s*{NUM}\s*(?:seconds?|secs?|s|ثاني[ةه]|ثواني|ثوان|sanya)(?!\w)")


def language(message):
    """ ar or en depends on the message language"""
    words = message.split()
    ar, en = sum(bool(ARABIC.search(w)) for w in words), sum(bool(LATIN.search(w)) for w in words)
    return "ar" if (ar and ar >= en) or FRANCO.search(message) else "en"


def reply_language(text):
    """The language of the answer"""
    return language(re.sub(r"\S*[\d_/\\]\S*", " ", text))


def asked_length(message):
    m = message.lower().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    m = CLOCK.sub(lambda x: f"{int(x[1]) * 60 + int(x[2])} sec", m)
    for pattern, new in WORDS:
        m = re.sub(pattern, new, m)
    m = re.sub(r"\b(" + "|".join(sorted(NUMBERS, key=len, reverse=True)) + r")\b",
               lambda x: str(NUMBERS[x.group(1)]), m)
    m = PLUS.sub(lambda x: f"{float(x[1]) * 60 + float(x[2]):g} sec", m)
    secs = []
    for n1, u1, n2, u2 in LENGTH.findall(m):
        per = lambda u: 60 if u.startswith(("min", "دق", "da2")) else 1
        secs.append(float(n1) * per(u1 or u2))
        if n2:
            secs.append(float(n2) * per(u2))
    return (min(secs), max(secs)) if secs else None


def asked_captions(message):
    m, found = message.lower(), None
    for hit in CAPTION.finditer(m):
        rest = m[hit.end():]
        before = " ".join(m[:hit.start()].split()[-3:])
        near = before + " " + " ".join(rest[re.match(r"\S*", rest).end():].split()[:4])
        if re.search(r"\b(?:no|without|remove|drop)\b(?:\s+\w+){0,2}\s*$|(?:بدون|من غير|مش عايز|مش عاوز|بلاش|شيل)"
                     r"\s*(?:\S+\s*)?$", before):
            return "none"
        ar = re.search(r"arabic|عربي|3arab", near)
        en = re.search(r"english|انجليز|إنجليز|انجلش|انكليز|englizy", near)
        if (ar and en) or re.search(r"\bboth\b|bilingual|الاتنين|الإتنين|الاثنين|اللغتين", near):
            return "ar+en"
        found = found or ("ar" if ar else "en" if en else None)
    return found


def default_captions(lang):
    return "ar+en" if lang == "en" else "ar"


VERTICAL = re.compile(r"vertical|portrait|tik ?tok|\breels?\b|\bshorts\b|\bstor(?:y|ies)\b|instagram|9\s*[:x/]\s*16|"
                      r"عمودي|طولي|ريل|تيك ?توك|تيكتوك|ستوري|شورتس|انستا|إنستا|\b2amoudy", re.I)
HORIZONTAL = re.compile(r"horizontal|landscape|youtube(?!\s*shorts)|16\s*[:x/]\s*9|أفقي|افقي|عرضي|يوتيوب(?!\s*شورتس)|"
                        r"\bofo2y", re.I)


def asked_format(message):
    v, h = VERTICAL.search(message), HORIZONTAL.search(message)
    return "9:16" if v and not h else "16:9" if h and not v else None


CLIP_NOUN = (r"(?:clips?|reels?|shorts?|videos?|tiktoks?|highlights?|كليب(?:ات|س)?|ريل(?:ز|ات|س)?|مقاطع|مقطع|"
             r"فيديوهات|فيديو|تيك ?توك)")
DUAL = re.compile(r"كليبين|ريلين|مقطعين|فيديوهين")


def asked_count(message):
    m = message.lower().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    if DUAL.search(m):
        return 2
    words = "|".join(sorted(map(re.escape, NUMBERS), key=len, reverse=True))
    unit = r"(?:minutes?|mins?|seconds?|secs?|دقيق\w*|دقايق|ثاني\w*|ثواني)\b"
    hit = re.search(rf"(?<![\d:.])(\d+|{words})\s+(?:(?!{unit})\w+\s+)?{CLIP_NOUN}(?!\w)", m)
    if hit:
        n = hit[1]
        return int(n) if n.isdigit() else NUMBERS[n]
    plural = r"\b(?:clips|reels|shorts|videos|tiktoks|highlights)\b|كليبات|ريلز|ريلات|مقاطع|فيديوهات"
    return None if re.search(plural, m) else 1


LONGER = re.compile(r"\blonger\b|\bextend|\blengthen|أطول|اطول|طوّل|طول(?:ه|ها|و)\b|زوّد|زود|\batwal\b|\bzawed\b", re.I)
SHORTER = re.compile(r"\bshorter\b|\bshorten|\btrim\b|أقصر|اقصر|قصّر|قصر(?:ه|ها|و)\b|قلّل|قلل|\ba2sar\b|\b2a[s9]ar\b", re.I)
DELTA = re.compile(r"\bby\b[^.]{0,20}?(?:\d|minute|second|half)|"
                   r"(?:\d|minutes?|seconds?|mins?|secs?)[^\d]{0,12}?\b(?:longer|shorter|more|less)\b|"
                   r"(?:زود|زوّد|قلل|قلّل|(?:أطول|اطول|أقصر|اقصر)\s*بـ?)\s*(?:\S+\s+)?"
                   r"(?:[\d٠-٩]|دقيق|ثاني|ثواني|ثوان|نص)", re.I)


def length_change(message):
    kind = "longer" if LONGER.search(message) else "shorter" if SHORTER.search(message) else None
    if not kind:
        return None
    amount = asked_length(message) if DELTA.search(message) else None
    return kind, amount[0] if amount else None


ROLES = {"en": {"host": "the host", "co-host": "the co-host", "guest": "the guest", "interviewer": "the interviewer",
                "interviewee": "the interviewee", "moderator": "the moderator", "panelist": "the panelist",
                "presenter": "the presenter", "audience": "someone in the audience"},
         "ar": {"host": "المقدم", "co-host": "المقدم المشارك", "guest": "الضيف", "interviewer": "المحاور",
                "interviewee": "الضيف", "moderator": "مدير الحوار", "panelist": "المشارك", "presenter": "مقدم العرض",
                "audience": "واحد من الجمهور"}}


def people_labels(speakers, lang):
    def role(p):
        r = ROLES[lang].get((p["role"] or "").lower())
        return r if r else None

    def named(p):
        script = ARABIC if lang == "ar" else LATIN
        return bool(p["name"]) and (bool(script.search(p["name"])) or not role(p))
    plain = [role(p) for p in speakers if not named(p)]
    labels, seen = {}, {}
    for k, p in enumerate(speakers, 1):
        if named(p):
            labels[p["id"]] = p["name"]
            continue
        r = role(p)
        if r and plain.count(r) == 1:
            labels[p["id"]] = r
            continue
        seen[r] = seen.get(r, 0) + 1
        base = r if r else ("speaker" if lang == "en" else "المتحدث")
        if lang == "en" and base.startswith("the "):
            base = base[4:]
        labels[p["id"]] = f"{base} {seen[r] if r else k}"
    return labels


def name_people(text, labels):
    text = re.sub(r"\s*\(\s*SPEAKER_\d+\s*\)", "", text)
    return re.sub(r"SPEAKER_\d+", lambda m: labels.get(m[0], m[0]), text)


def title_problem(title, lang, said):
    if CJK.search(title):
        return "the title has Chinese letters"
    ar, en = len(ARABIC.findall(title)), len(LATIN.findall(title))
    if lang == "en" and ar:
        return "the user wrote in English: write the title in English (no Arabic letters)"
    if lang == "ar" and en > ar:
        return "the user wrote in Arabic: write the title in Arabic"
    words = re.findall(r"\w+", title.lower())
    if len(words) >= 4 and " ".join(words) in " ".join(re.findall(r"\w+", said.lower())):
        return "the title is copied from the transcript: write a catchy title that says what the clip is about"
    if len(words) > 10:
        return "the title is too long: at most 8 words"
    return ""


class FocusWish(BaseModel):                    #the LLM answer who to show and how much"
    person: str = Field(description="who the user wants on screen: a role (guest, host, ...) or a name; "
                                    "'not_asked' if nobody")
    level: Literal["not_asked", "only", "mostly", "more"]
    share: int | None = Field(None, description="a percentage the user typed for that person (70% -> 70), else null")


FOCUS_PROMPT = """You read ONE request for a video clip and say WHO the user wants to see on screen and HOW MUCH.
Only a request to SHOW / FOCUS ON / ZOOM ON a person counts ("focus on", "show", "ركز على", "خلي ... يظهر", "rakez 3ala").
A person who is only part of the TOPIC is NOT a request to show them ("where the guest explains ...", "the guest's
opinion", "the host asks the guest", "اللي الضيف بيتكلم فيه") -> "not_asked".
- "focus on the guest", "ركز على الضيف", "show the host", "only the guest", "الضيف بس" -> "only"
- "mostly the guest", "most of the time", "أغلب الوقت", "but also the others a little bit" -> "mostly"
- "show the guest more", "show Islam more", "a bit more of the guest", "زود الضيف شوية" -> "more"
- a percentage for that person ("the guest 70% of the time") -> "mostly" and share 70
Examples:
"make a clip about salaries" -> {{"person": "not_asked", "level": "not_asked", "share": null}}
"clip where the host asks the guest about his salary" -> {{"person": "not_asked", "level": "not_asked", "share": null}}
"اعمل كليب دقيقة عن الشغل وركز على المذيع" -> {{"person": "host", "level": "only", "share": null}}
"30 second reel about AI, mostly the guest" -> {{"person": "guest", "level": "mostly", "share": null}}
"clip about CVs, show the host more" -> {{"person": "host", "level": "more", "share": null}}
"reel about jobs with the guest on screen 80% of the time" -> {{"person": "guest", "level": "mostly", "share": 80}}
Request: {message}"""


def focus_wish(answer, message):
    level = None if answer.level == "not_asked" or answer.person.strip().lower() in ("", "not_asked") else answer.level
    share = answer.share if answer.share and 10 <= answer.share <= 100 and re.search(
        rf"(?<!\d){answer.share}(?!\d)", message) else None
    return {"person": answer.person if level else "", "level": level, "share": share if level else None}


def read_focus(message, model, keep_alive="2m", num_ctx=8192):
    from .search import ollama_client
    extra = {"think": False} if model.startswith("qwen3") else {}
    r = ollama_client().chat(model=model, messages=[{"role": "user", "content": FOCUS_PROMPT.format(message=message)}],
                             format=FocusWish.model_json_schema(), keep_alive=keep_alive,
                             options={"temperature": 0, "num_ctx": num_ctx}, **extra)
    return focus_wish(FocusWish.model_validate_json(r.message.content), message)
