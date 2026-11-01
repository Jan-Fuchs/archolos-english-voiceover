r"""Second unattended pass, after run_rest.py has finished (resumable: start it again; finished steps are skipped).
  1. voices for one-off NPCs the script never ties to a named character (slum guardian, spies, trader, ...): gender and
     voice features from the Polish actor's audio (staged by stage_extra_cast.py -> work/extra_cast.json), designed
     with recast_auto.py
  2. their 210 lines + every grunt / yawn / scream in the speaker's own voice (work/grunt_lines.tsv: the interjection is
     written as text, e.g. "Argh!", and the direction shapes it - Breeze drops non-verbal cues without text)
  3. up to three more takes (seed offsets 2, 3, 4) for every line that still fails QA, so fewer lines fall back to the pack
  4. pack once the game is closed
Status: work/run_extras.status.   usage: .venv\Scripts\python run_extras.py
"""
import glob, json, os, subprocess, sys, time
from gamecheck import game_running
P = os.path.dirname(os.path.abspath(__file__)); os.chdir(P); PY = sys.executable; PYA = os.path.join(P, ".venv-audit", "Scripts", "python.exe")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ST = os.path.join("work", "run_extras.status")


def say(m):
    l = f"{time.strftime('%m-%d %H:%M:%S')}  {m}"; print(l, flush=True); open(ST, "a", encoding="utf-8").write(l + "\n")


def run(exe, *a, env=None):
    say(">> " + " ".join(a)[:300]); r = subprocess.run([exe, *a], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    for l in (r.stdout.strip().splitlines() or [""])[-3:]: say("   " + l)
    if r.returncode: say("   STDERR: " + r.stderr[-500:])
    return r.returncode


def done(s): return os.path.exists(f"work/run_extras.{s}.done")
def mark(s): open(f"work/run_extras.{s}.done", "w").write(time.strftime("%Y-%m-%d %H:%M:%S"))


def tsv(p):
    L = open(p, encoding="utf-8").read().splitlines(); h = L[0].split("\t"); return [dict(zip(h, l.split("\t"))) for l in L[1:] if l]


def main():
    say("=== run_extras start (waiting for run_rest.py to finish)")
    while not (os.path.exists("work/run_rest.status") and "=== run_rest done" in open("work/run_rest.status", encoding="utf-8").read()):
        time.sleep(60)
    # 1. cast the one-off NPCs
    if not done("cast"):
        ex = json.load(open("work/extra_cast.json", encoding="utf-8"))
        script = {r["speaker"]: r["gender"] for r in tsv("work/gender_script.tsv")}
        feats = json.load(open("work/cast_features.json", encoding="utf-8"))
        gl = open("work/gender_llm.tsv", encoding="utf-8").read().splitlines(); have_g = {l.split("\t")[0] for l in gl}
        prompt = open("refs/cast/prompt_text", encoding="utf-8").read().splitlines(); have_p = {l.split("|")[0] for l in prompt}
        cast = open("work/cast.tsv", encoding="utf-8").read().splitlines(); have_c = {l.split("\t")[0] for l in cast}
        for spk, v in ex.items():
            g = script.get(spk, v["gender"]); ft = v["features"]
            feats[spk] = {k: ft[k] for k in ("f0", "jitter", "centroid", "rate", "sec", "lines")}
            if spk not in have_g: gl.append(f"{spk}\t{g}\tpolish audio classifier p_female={v['p_female']}")
            if spk not in have_p: prompt.append(f"{spk}|{v['anchor_line']}")
            if spk not in have_c: cast.append(f"{spk}\t{ft['lines']}\t{ft['sec']}\t{ft['f0']:.0f}\t{ft['jitter']:.3f}\t{ft['centroid']:.0f}\t{ft['rate']:.1f}\t\t(new)\t")
        json.dump(feats, open("work/cast_features.json", "w", encoding="utf-8"))
        open("work/gender_llm.tsv", "w", encoding="utf-8").write("\n".join(gl) + "\n")
        open("refs/cast/prompt_text", "w", encoding="utf-8").write("\n".join(prompt) + "\n")
        open("work/cast.tsv", "w", encoding="utf-8").write("\n".join(cast) + "\n")
        say(f"cast {len(ex)} one-off voices: {', '.join(ex)}")
        run(PYA, "recast_auto.py", ",".join(ex), "--seeds", "7,11,23,41", "--apply", "--threads", "6")
        mark("cast")
    # 2. one-off NPC lines + grunts
    if not done("extra"):
        while not os.path.exists("work/batches/extranpc_00.dir.tsv"): time.sleep(60)
        rows = tsv("work/extra_npc_lines.tsv") + tsv("work/grunt_lines.tsv")
        seen = set()
        with open("work/extra_lines.tsv", "w", encoding="utf-8") as f:
            f.write("speaker\twav\ttext\tblock\ttier\n")
            for r in rows:
                if r["wav"] in seen: continue
                seen.add(r["wav"]); f.write(f"{r['speaker']}\t{r['wav']}\t{r['text']}\t\tfiller\n")
        say(f"one-off NPC lines + grunts: {len(seen)} lines")
        run(PY, "redo_lines.py", "--lines", "work/extra_lines.tsv", "--directions", "work/batches/extranpc_*.dir.tsv", "work/batches/grunts.dir.tsv", "--keep", "--no-pack")
        mark("extra")
    # 3. more takes for lines that still fail QA
    if not done("retake"):
        sets = ["work/stage1_lines.tsv", "work/stage1b_lines.tsv", "work/svm_all_lines.tsv"] + sorted(glob.glob("work/rest_*_lines.tsv")) + ["work/extra_lines.tsv"]
        line = {}
        for s in sets:
            if os.path.exists(s):
                for r in tsv(s): line[r["wav"].upper()] = r
        inst = {os.path.basename(l.strip()).upper() for l in open("work/installed.txt", encoding="utf-8") if l.strip()}
        for off in (2, 3, 4):
            flagged = {r["wav"].upper() for r in tsv("work/qa_flags.tsv")}
            todo = sorted(w for w in flagged if w in line and w not in inst)
            say(f"re-take round seed offset {off}: {len(todo)} lines still failing QA")
            if not todo: break
            with open("work/retake_lines.tsv", "w", encoding="utf-8") as f:
                f.write("speaker\twav\ttext\tblock\ttier\n")
                for w in todo: r = line[w]; f.write(f"{r['speaker']}\t{w}\t{r['text']}\t\t{r.get('tier', 'filler') or 'filler'}\n")
            open("work/retake_redo.tsv", "w", encoding="utf-8").write("wav\n" + "\n".join(todo) + "\n")
            run(PY, "render_all.py", "--lines", "work/retake_lines.tsv", "--directions", "work/batches/*.dir.tsv", "--redo", "work/retake_redo.tsv", "--seed-offset", str(off))
            qa = open("work/qa_all.tsv", encoding="utf-8").read().splitlines(); drop = set(todo)
            open("work/qa_all.tsv", "w", encoding="utf-8").write("\n".join([qa[0]] + [l for l in qa[1:] if l.split("\t")[0].upper() not in drop]) + "\n")
            run(PY, "qa_all.py", "--lines", "work/retake_lines.tsv"); run(PY, "qa_refine.py")
            run(PY, "install_stage.py", "--lines", "work/retake_lines.tsv", "--skip-flagged")
            inst = {os.path.basename(l.strip()).upper() for l in open("work/installed.txt", encoding="utf-8") if l.strip()}
        mark("retake")
    # 4. pack
    waited = 0
    while game_running():
        if waited == 0: say("PACK WAITING: close the game to repack the archives")
        time.sleep(30); waited += 30
    run(PY, "pack_mod.py")
    say("=== run_extras done")


if __name__ == "__main__":
    main()
