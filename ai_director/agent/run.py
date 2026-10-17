import sys
import time

from ..common.io import session_from_argv
from .agent import chat


def show(out, seconds):
    for k, st in enumerate(out["steps"], 1):
        print(f"  step {k}: {st['tool']}({st['args']}) -> {st['summary']}")
    print(f"agent> {out['reply']}")
    for c in out["clips"]:
        print(f"  clip {c['id']}: {c['start']}-{c['end']} s, {c['format']}, {c['file']}  \"{c['title']}\"")
    print(f"  ({seconds:.1f} s)")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")       #Arabic in any terminal
    s = session_from_argv()
    if len(sys.argv) > 2:                                             #one request
        t0 = time.time()
        show(chat(s, " ".join(sys.argv[2:])), time.time() - t0)
        return
    history = []
    while True:                                                       #a chat that remembers the last messages
        message = input("you> ").strip()
        if message.lower() in ("exit", "quit", "خروج"):
            break
        t0 = time.time()
        out = chat(s, message, history)
        show(out, time.time() - t0)
        history += [{"role": "user", "content": message}, {"role": "assistant", "content": out["reply"]}]


if __name__ == "__main__":
    main()
