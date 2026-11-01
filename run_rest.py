r"""Unattended render of all dialogue beyond chapter 1 (resumable: start it again after any stop; finished blocks are skipped).
Line sets come from build_rest.py (work/rest_<block>_lines.tsv), directions from work/batches/rest<block>_*.dir.tsv.
  1. per block (1, 2, world, 3, 4, 5, 6): wait until every line of the block has a direction, then render, QA, one
     re-take, install (redo_lines.py --keep), and pack if the game is closed at that moment
  2. at the end, wait for the game to close and pack once more
Status: work/run_rest.status. Needs the audio server (tools\audiocpp\audiocpp_server.exe --config server.json).
usage: .venv\Scripts\python run_rest.py
"""
import glob, os, subprocess, sys, time
from gamecheck import game_running
P = os.path.dirname(os.path.abspath(__file__)); os.chdir(P); PY = sys.executable
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ST = os.path.join("work", "run_rest.status"); BLOCKS = ["1", "2", "world", "3", "4", "5", "6"]


def say(m):
    l = f"{time.strftime('%m-%d %H:%M:%S')}  {m}"; print(l, flush=True); open(ST, "a", encoding="utf-8").write(l + "\n")


def run(exe, *a):
    say(">> " + " ".join(a)); r = subprocess.run([exe, *a], capture_output=True, text=True, encoding="utf-8", errors="replace")
    for l in (r.stdout.strip().splitlines() or [""])[-3:]: say("   " + l)
    if r.returncode: say("   STDERR: " + r.stderr[-500:])
    return r.returncode


def done(step): return os.path.exists(os.path.join("work", f"run_rest.{step}.done"))
def mark(step): open(os.path.join("work", f"run_rest.{step}.done"), "w").write(time.strftime("%Y-%m-%d %H:%M:%S"))


def wavs(path, col):
    L = open(path, encoding="utf-8").read().splitlines(); i = L[0].split("\t").index(col)
    return {l.split("\t")[i].upper() for l in L[1:] if l.count("\t") >= i}


def directions_ready(b):
    have = set()
    for f in glob.glob(f"work/batches/rest{b}_*.dir.tsv"): have |= wavs(f, "wav")
    return not (wavs(f"work/rest_{b}_lines.tsv", "wav") - have)


def main():
    say("=== run_rest start")
    for b in BLOCKS:
        if done(f"block_{b}"): continue
        waited = 0
        while not directions_ready(b):
            if waited % 1800 == 0: say(f"block {b}: waiting for its direction batches")
            time.sleep(60); waited += 60
        n = sum(1 for _ in open(f"work/rest_{b}_lines.tsv", encoding="utf-8")) - 1
        say(f"=== block {b}: {n} lines")
        run(PY, "redo_lines.py", "--lines", f"work/rest_{b}_lines.tsv", "--directions", f"work/batches/rest{b}_*.dir.tsv", "--keep", "--pack-if-free")
        mark(f"block_{b}")
    say("all blocks rendered; final pack once the game is closed")
    while game_running(): time.sleep(30)
    run(PY, "pack_mod.py")
    say("=== run_rest done")


if __name__ == "__main__":
    main()
