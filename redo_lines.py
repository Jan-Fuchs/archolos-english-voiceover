r"""Re-render a set of already-installed lines end to end (new directions, new anchors): render with --overwrite, QA
(ASR round-trip), one re-take of flagged lines with another seed, QA again, then install. A line that still fails is
removed from the loose files and the inventory, so the original pack plays instead of an outdated take. Packs at the
end once no real Gothic2.exe runs (--no-pack to skip). Needs the audio server.
usage: .venv\Scripts\python redo_lines.py --lines work/x_lines.tsv --directions "work/batches/a_*.dir.tsv" ... [--no-pack]
Later --directions patterns override earlier ones for the same wav.
"""
import argparse, os, subprocess, sys, time
from gamecheck import game_running
P = os.path.dirname(os.path.abspath(__file__)); os.chdir(P); PY = sys.executable
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
LOG = os.path.join("work", "redo_lines.status")


def say(msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"; print(line, flush=True); open(LOG, "a", encoding="utf-8").write(line + "\n")


def run(*a, env=None):
    say(">> " + " ".join(a))
    r = subprocess.run([PY, *a], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    for l in (r.stdout.strip().splitlines() or [""])[-2:]: say("   " + l)
    if r.returncode: say("   STDERR: " + r.stderr[-400:])
    return r.returncode


def wavs_of(path):
    return {l.split("\t")[1].upper() for l in open(path, encoding="utf-8").read().splitlines()[1:] if "\t" in l}


def drop_qa_rows(wavs):
    p = "work/qa_all.tsv"; L = open(p, encoding="utf-8").read().splitlines()
    open(p, "w", encoding="utf-8").write("\n".join([L[0]] + [l for l in L[1:] if l.split("\t")[0].upper() not in wavs]) + "\n")


def flagged():
    return {l.split("\t")[0].upper() for l in open("work/qa_flags.tsv", encoding="utf-8").read().splitlines()[1:]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--lines", required=True); ap.add_argument("--directions", nargs="*", default=[])
    ap.add_argument("--no-pack", action="store_true"); ap.add_argument("--keep", action="store_true", help="new lines: keep existing renders and QA rows (resumable)")
    ap.add_argument("--pack-if-free", action="store_true", help="pack only if the game is closed right now, never wait"); a = ap.parse_args()
    wavs = wavs_of(a.lines); say(f"=== redo {a.lines}: {len(wavs)} lines")
    run("render_all.py", "--lines", a.lines, "--directions", *a.directions, *([] if a.keep else ["--overwrite"]))
    if not a.keep: drop_qa_rows(wavs)
    run("qa_all.py", "--lines", a.lines); run("qa_refine.py")
    bad = flagged() & wavs
    if bad:
        retake = "work/redo_retake.tsv"
        open(retake, "w", encoding="utf-8").write("wav\n" + "".join(w + "\n" for w in sorted(bad)))
        say(f"re-take {len(bad)} flagged lines with seed offset 1")
        run("render_all.py", "--lines", a.lines, "--directions", *a.directions, "--redo", retake, "--seed-offset", "1")
        drop_qa_rows(bad); run("qa_all.py", "--lines", a.lines); run("qa_refine.py")
    bad = flagged() & wavs
    inv = "work/installed.txt"; keep = []; pruned = 0
    for l in open(inv, encoding="utf-8").read().splitlines():
        if os.path.basename(l).upper() in bad:
            if os.path.exists(l): os.remove(l)
            pruned += 1
        else: keep.append(l)
    open(inv, "w", encoding="utf-8").write("\n".join(keep) + "\n")
    say(f"{len(bad)} lines still flagged after the re-take -> left to the pack ({pruned} old takes removed)")
    run("install_stage.py", "--lines", a.lines, "--skip-flagged")
    if a.no_pack: say("=== done (pack skipped)"); return
    if a.pack_if_free and game_running(): say("=== done (game running, pack later)"); return
    waited = 0
    while game_running():
        if waited == 0: say("PACK WAITING: close the game to repack the archives")
        time.sleep(30); waited += 30
    run("pack_mod.py")
    say("=== done")


if __name__ == "__main__":
    main()
