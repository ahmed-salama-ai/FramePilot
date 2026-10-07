# ai_director/highlights/run.py — stage 7: interest curve -> candidates -> LLM picks -> clips -> highlights.json
#   python -m ai_director.highlights.run data/sessions/s01
# Owner: Sara Walid (taken over by Ahmed Salama)
from pydantic import TypeAdapter

from ..common.io import read_json, session_from_argv, write_json
from ..common.schemas import Highlight
from .clips import make_clips
from .interest import interest_curve
from .select import candidates, pick


def main(s, ask=None):
    meta = read_json(s / "session.json")
    ev = interest_curve(s)
    (s / "highlights").mkdir(exist_ok=True)
    ev.to_csv(s / "highlights" / "interest.csv", index=False)            # for charts and checking
    cands = candidates(ev, read_json(s / "transcript.json"), meta["duration"])
    print(f"  {len(cands)} candidate moments: " + ", ".join(f"{c['start']:.0f}-{c['end']:.0f} s" for c in cands))
    items = make_clips(s, pick(cands, meta["language"], ask))
    TypeAdapter(list[Highlight]).validate_python(items)                 # follows the contract
    write_json(s / "highlights.json", items)                            # LAST: the done file of this stage
    print(f"  highlights.json: {len(items)} highlights")
    return items


if __name__ == "__main__":
    main(session_from_argv())
