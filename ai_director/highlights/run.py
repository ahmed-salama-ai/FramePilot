from pydantic import TypeAdapter

from ..common.io import read_json, session_from_argv, write_json
from ..common.schemas import Highlight
from .clips import make_clips
from .interest import interest_curve
from .publish import make_publish
from .select import candidates, pick


def main(s, ask=None, publish_ask=None, extras=None):
    """ask / publish_ask: stand-ins for the text model (tests). With a test `ask` and no `publish_ask` the publish kit
    is skipped (no real request in tests)"""
    meta = read_json(s / "session.json")
    ev = interest_curve(s)
    (s / "highlights").mkdir(exist_ok=True)
    ev.to_csv(s / "highlights" / "interest.csv", index=False)            #for charts and checking
    cands = candidates(ev, read_json(s / "transcript.json"), meta["duration"])
    print(f"  {len(cands)} candidate moments: " + ", ".join(f"{c['start']:.0f}-{c['end']:.0f} s" for c in cands))
    items = make_clips(s, pick(cands, meta["language"], ask))
    TypeAdapter(list[Highlight]).validate_python(items)                 #follows the contract
    if publish_ask or ask is None:                                      #chapters, summary, posts
        try:
            p = make_publish(s, items, ask=publish_ask)
            print(f"  publish.json: {len(p['chapters'])} chapters, {len(p['posts'])} social posts")
        except Exception as e:                                          #never blocks the highlights
            print(f"  WARNING: no publish kit ({type(e).__name__}: {str(e)[:120]}); make it later with "
                  f"python -m ai_director.highlights.publish {s}")
    if extras if extras is not None else ask is None:                   #article, trailer, thumbnails
        from ..director.thumbnail import make_thumbnails
        from .article import make_article
        from .trailer import make_trailer
        for name, make in (("article", lambda: make_article(s)), ("trailer", lambda: make_trailer(s)),
                           ("thumbnails", lambda: make_thumbnails(s, highlights=items))):
            try:
                make()
                print(f"  {name}: done")
            except Exception as e:
                print(f"  WARNING: no {name} ({type(e).__name__}: {str(e)[:120]}); the web page can make it later")
    write_json(s / "highlights.json", items)                            #LAST: the done file of this stage
    print(f"  highlights.json: {len(items)} highlights")
    return items


if __name__ == "__main__":
    main(session_from_argv())
