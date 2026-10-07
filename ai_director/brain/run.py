# ai_director/brain/run.py — stage 4: AI Brain (vision model scene understanding + director modes) -> scene.jsonl
#   python -m ai_director.brain.run data/sessions/s01
# Owner: Eslam ElKharbotly
from ..common.io import session_from_argv
from .scene import run

if __name__ == "__main__":
    s = session_from_argv()
    print(f"  AI Brain on {s}")
    run(s)
