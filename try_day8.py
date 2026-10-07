# try_day8.py - Day 8 try-out (delete it afterwards, it is not part of the project)
from pathlib import Path

from ai_director.director.render import render_clip, render_program
from ai_director.director.run import make_cuts

s = Path("data/sessions/s01")
render_clip(s, 300, 330, "clips/test_169.mp4")                                      # 16:9 from the AI edit
render_clip(s, 300, 330, "clips/test_916.mp4", fmt="9:16", source=3, crop_x=0.49)   # 9:16, camera 3 only
print("2 clips done: data/sessions/s01/clips/")
cuts = make_cuts(s, boost={"cam": 3, "factor": 1.3}, out="cuts_v2.json")             # the agent's "restyle"
render_program(s, cuts, out="program_v2.mp4")
print("done: data/sessions/s01/program_v2.mp4")
