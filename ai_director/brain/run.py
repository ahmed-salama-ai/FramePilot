from ..common.io import session_from_argv
from .scene import run

if __name__ == "__main__":
    s = session_from_argv()
    print(f"  AI Brain on {s}")
    run(s)
