r"""Unattended run for ALL stock-line (SVM) voice sets. Resumable: re-run the same command after any interruption and it
continues (rendered files, QA rows and installed files are skipped). Steps:
  1. directions for every voiced SVM line from the (token,text) direction pool  -> work/batches/svm_all.dir.tsv
  2. line set with the anchor speaker per voice set (work/svm_voices.tsv)       -> work/svm_all_lines.tsv
  3. render (render_all.py)   4. QA (qa_all.py + qa_refine.py)   5. install (install_stage.py)
  6. pack (pack_mod.py) as soon as the game is closed (gamecheck.py)
Needs the audio server running: tools\audiocpp\audiocpp_server.exe --config server.json --ui
usage: .venv\Scripts\python svm_run.py [--no-pack] [--only 70,65]      status: work/svm_run.status, log: work/svm_run.log
"""
import glob, json, os, re, subprocess, sys, time, urllib.request
from gamecheck import game_running
P = os.path.dirname(os.path.abspath(__file__)); os.chdir(P); PY = sys.executable
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
STATUS = os.path.join("work", "svm_run.status")
GRUNT = re.compile(r"^[^A-Za-z]*(a+r+g+h*|a+h+|u+g+h+|o+h+|h+m+|argh|ugh|hmpf|hm|pff+|ouch|ow|oof|ah|oh|ha+|he+h*)[^A-Za-z]*$", re.I)


def status(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"; print(line, flush=True)
    open(STATUS, "a", encoding="utf-8").write(line + "\n")


def run(*a):
    status(">> " + " ".join(a))
    r = subprocess.run([PY, *a], capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (r.stdout.strip().splitlines() or [""])[-1]; status(f"   {tail}")
    if r.returncode: status("   STDERR: " + r.stderr[-400:])
    return r.returncode


def server_up():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/v1/models", timeout=5) as r: return r.status == 200
    except Exception: return False


def main():
    no_pack = "--no-pack" in sys.argv
    only = set(next((a.split("=", 1)[1] if "=" in a else sys.argv[sys.argv.index(a) + 1] for a in sys.argv if a.startswith("--only")), "").split(",")) - {""}
    status(f"=== svm_run start (only={sorted(only) or 'all'})")
    if not server_up():
        status("audio server not reachable at 127.0.0.1:8080 - start tools\\audiocpp\\audiocpp_server.exe --config server.json --ui and re-run"); sys.exit(2)
    # 1. directions
    rows = [l.rstrip("\n").split("\t") for l in open("work/ou_lines.tsv", encoding="utf-8")][1:]
    svm = [(r[0], r[1].upper(), r[2]) for r in rows if len(r) >= 3 and r[1].upper().startswith("SVM_") and r[1].split("_")[1].isdigit()]
    text_of = {w: t for _, w, t in svm}
    key = lambda w: (re.sub(r"^SVM_\d+_", "", w), text_of[w])
    pool = {}
    for f in glob.glob("work/batches/svm*_0*.dir.tsv"):
        for l in open(f, encoding="utf-8").read().splitlines()[1:]:
            r = l.split("\t")
            if len(r) == 2 and r[0].upper() in text_of and 6 <= len(r[1].split()) <= 18 and not re.search(r"sigh|breath|exhal|laugh|chuckl", r[1], re.I):
                pool[key(r[0].upper())] = r[1]
    voiced = [(b, w, t) for b, w, t in svm if not re.search(r"<[^>]+>", t) and not GRUNT.match(t.strip())]
    with open("work/batches/svm_all.dir.tsv", "w", encoding="utf-8") as f:
        f.write("wav\tinstruction\n"); n_dir = 0
        for b, w, t in voiced:
            d = pool.get(key(w))
            if d: f.write(f"{w}\t{d}\n"); n_dir += 1
    status(f"directions: {n_dir}/{len(voiced)} voiced stock lines covered ({len(pool)} distinct); the rest get the default direction")
    # 2. line set with anchor speakers
    anchors = {}
    for l in open("work/svm_voices.tsv", encoding="utf-8").read().splitlines()[1:]:
        r = l.split("\t"); anchors[int(r[0])] = r[1]
    missing_anchor = sorted({a for a in anchors.values() if not os.path.exists(f"refs/cast/{a}.wav")})
    if missing_anchor: status(f"missing anchors: {missing_anchor}"); sys.exit(3)
    n = 0
    with open("work/svm_all_lines.tsv", "w", encoding="utf-8") as f:
        f.write("speaker\twav\ttext\tblock\ttier\n")
        for b, w, t in voiced:
            v = int(w.split("_")[1])
            if only and str(v) not in only: continue
            if v not in anchors: continue
            f.write(f"{anchors[v]}\t{w}\t{t}\t{b}\tfiller\n"); n += 1
    status(f"line set: {n} lines across {len({int(w.split('_')[1]) for _, w, _ in voiced if not only or w.split('_')[1] in only})} voice sets")
    # 3-5
    if run("render_all.py", "--lines", "work/svm_all_lines.tsv", "--directions", "work/batches/svm_all.dir.tsv"): status("render reported errors; re-run to retry")
    run("qa_all.py", "--lines", "work/svm_all_lines.tsv")
    run("qa_refine.py")
    # prune: a line flagged now but installed earlier must leave the Speech folder and the inventory (the pack takes over)
    flagged = {l.split("\t")[0].upper() for l in open("work/qa_flags.tsv", encoding="utf-8").read().splitlines()[1:]}
    inv = "work/installed.txt"; keep = []; pruned = 0
    for l in open(inv, encoding="utf-8").read().splitlines():
        if os.path.basename(l).upper() in flagged:
            if os.path.exists(l): os.remove(l)
            pruned += 1
        else: keep.append(l)
    open(inv, "w", encoding="utf-8").write("\n".join(keep) + "\n"); status(f"pruned {pruned} previously installed lines that are now flagged")
    run("install_stage.py", "--lines", "work/svm_all_lines.tsv", "--skip-flagged")
    # 6. pack
    if no_pack: status("pack skipped (--no-pack)"); status("=== svm_run done"); return
    waited = 0
    while game_running():
        if waited == 0: status("game is running - waiting for it to close before packing")
        time.sleep(30); waited += 30
    D = os.path.join(os.environ.get("ARCHOLOS_DIR", "C:/Program Files (x86)/Steam/steamapps/common/TheChroniclesOfMyrtana"), "Data")
    for f in glob.glob(os.path.join(D, "KM_SpeechJAN*.mod")):
        open(f, "r+b").close()
    r = subprocess.run([PY, "pack_mod.py"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    for l in r.stdout.strip().splitlines(): status("   " + l)
    status("=== svm_run done" + ("" if r.returncode == 0 else " (PACK FAILED)"))


if __name__ == "__main__":
    main()
