"""Build direction batches as whole scenes (v3): every conversation in true spoken order (trailing _NN index, not Ou.bin
file order), choice branches shown as separate alternatives after their opening (dialogue is a tree), the real speaker
per line (line set column -> work/speaker_script.tsv -> file name), and only the target lines marked for directing.
Lines of the scene that already have a direction are shown with it, so the new ones stay continuous with them.

Writes <prefix>_NN.ctx.txt (prompt + scenes, <= --max target lines per file, scenes never split) and
<prefix>_NN.targets.tsv (the wav list each batch must answer). Give each ctx file to a fresh chat/subagent, which writes
<prefix>_NN.dir.tsv; then `python make_scenes.py --check <prefix>` validates every batch.

usage: python make_scenes.py --lines work/x_lines.tsv --prefix work/batches/x [--max 150]
       python make_scenes.py --check work/batches/x
"""
import argparse, glob, os, re, sys
from collections import defaultdict
P = os.path.dirname(os.path.abspath(__file__)); W = os.path.join(P, "work")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# chapter variants and duplicate tokens of one character -> the cast token that holds the voice
ALIAS = {"CAPTAINARCHOLOS": "CAPTAIN", "BORRIS": "BORIS"}

SYSTEM = """You write delivery directions for a voice actor performing lines from The Chronicles of Myrtana: Archolos, a Gothic II total conversion. The register is Gothic: grounded, unhurried, dry, understated; grave people in a hard medieval world. Never chirpy, never theatrical. MARVIN is the player character, a young man with no illusions.

You get WHOLE scenes, each line in its true spoken order, as `[FILE] SPEAKER: text`. Lines marked `*` need a direction from you. Unmarked lines are context only; if they were directed earlier, their direction follows as `(done: ...)` - stay continuous with it, never output it.

Dialogue is a tree. `-- Opening --` is said when the player picks the topic. Each `-- Branch: X --` is ONE alternative the player may choose after the part it hangs on (or a later follow-up on another day); sibling branches never play one after another. Carry mood and pace from the opening into each branch, but never from one branch into its sibling.

Direct each scene as one continuous performance, not a list of separate lines:
1. Continuity. Consecutive lines of the same character must sound like the same person a moment later. Keep tone and pace continuous unless the text itself turns.
2. Motivated turns. When the mood turns, make the turn audible INSIDE the direction rather than cutting to a new mood cold: e.g. "starts level, hardens on the last clause", "quieter than before, the fear surfacing", "a shade quicker, the irritation showing". A pace change between two consecutive lines of the same speaker must be earned by the words and is usually a shade, not a leap.
3. Reactions. A line that answers someone should carry what was just heard (surprise, irritation, relief), not only its own words.
4. Pace rule. The default for every line is unhurried; say so explicitly ("slow", "unhurried", "takes his time"). Call for brisk pace only when the character is plainly impatient, urgent, angry or mid-action; then the speed itself carries the meaning.
5. The voice model cannot produce sighs, breaths, laughs, coughs or any non-verbal sound. Never ask for them. Shape every transition with tone, weight, volume and pace inside the spoken words.
6. Read the situation from the words: a dying man, a threat, a sale, a joke between friends. Do not invent context that is not in the scene.

Write ONE direction per `*` line: 6-18 words describing HOW it is said, not what it means. Prefer restraint; most lines are quiet. Use he/she to match the speaker where needed; if unsure, avoid pronouns.

Output: a TSV file with the header `wav<TAB>instruction` and one row per `*` line, in the order given, the file name exactly as shown in brackets. Nothing else in the file."""


def tsv(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8")]
    return [dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])]


TAIL = re.compile(r"_(\d+)_(\d+)(?:_([A-Z]))?\.WAV$")


def topic(wav):
    """Info function a line belongs to: file name minus _<n>_<idx>[_A]; trialogue files drop their owner token."""
    w = wav.upper(); k = TAIL.sub("", w)
    if k == w: k = w[:-4]
    if k.startswith("TRIA_"): k = "TRIA_" + k.split("_", 2)[2] if k.count("_") >= 2 else k
    return k


def order(wav):
    m = TAIL.search(wav.upper())
    return (int(m.group(2)), m.group(3) or "") if m else (0, "")


def load_dirs():
    d = {}
    for f in glob.glob(os.path.join(W, "batches", "*.dir.tsv")):
        for r in tsv(f):
            if r.get("instruction"): d[r["wav"].upper()] = r["instruction"]
    return d


def build(a):
    ou = [r for r in tsv(os.path.join(W, "ou_lines.tsv")) if r["wav"].upper().endswith(".WAV") and not r["wav"].upper().startswith("SVM_")]
    text = {r["wav"].upper(): r["text"] for r in ou}
    spk = {}
    for r in tsv(os.path.join(W, "speaker_script.tsv")):
        if not r["speaker"].startswith("?"): spk[r["wav"].upper()] = r["speaker"].upper()
    targets = []
    for r in tsv(a.lines):
        w = r["wav"].upper(); targets.append(w)
        if r.get("speaker"): spk[w] = r["speaker"].upper()
    def speaker(w):
        if w in spk: s = spk[w]
        elif re.search(r"_15_\d+(_[A-Z])?\.WAV$", w): s = "MARVIN"
        else: m = re.match(r"(?:DIA|TRIA)_([^_]+)_", w); s = m.group(1) if m else "NPC"
        return ALIAS.get(s, s)
    tset = set(targets); dirs = load_dirs()
    by_topic = defaultdict(list)
    for r in ou:
        if r["wav"].upper() not in by_topic[topic(r["wav"])]: by_topic[topic(r["wav"])].append(r["wav"].upper())
    keys = sorted(by_topic)
    parent = {}
    for k in keys:                                                   # parent = longest other topic that is a "_"-prefix
        best = None
        for j in range(len(k) - 1, 0, -1):
            if k[j] == "_" and k[:j] in by_topic: best = k[:j]; break
        parent[k] = best
    root = {}
    for k in keys:
        r = k
        while parent[r]: r = parent[r]
        root[k] = r
    kids = defaultdict(list)
    for k in keys:
        if parent[k]: kids[parent[k]].append(k)
    scenes = defaultdict(int)                                        # root -> number of target lines inside
    for w in targets:
        if w in text: scenes[root[topic(w)]] += 1
    missing = [w for w in targets if w not in text]
    if missing: print(f"warning: {len(missing)} target lines not in ou_lines.tsv (e.g. {missing[:3]})")

    def render(k, label, out):
        out.append(f"-- {label} --")
        for w in sorted(by_topic[k], key=order):
            mark = "*" if w in tset else " "
            done = f"   (done: {dirs[w]})" if w not in tset and w in dirs else ""
            out.append(f"{mark}[{w}] {speaker(w)}: {text[w]}{done}")
        for i, c in enumerate(sorted(kids[k]), 1):
            render(c, f"Branch: {c[len(k) + 1:]} ({i} of {len(kids[k])}, after {'the opening' if label == 'Opening' else label.split(' (')[0]})", out)

    batches, cur, n = [], [], 0
    for r in sorted(scenes):                                         # alphabetical = grouped by owner
        if cur and n + scenes[r] > a.max: batches.append(cur); cur, n = [], 0
        cur.append(r); n += scenes[r]
    if cur: batches.append(cur)
    os.makedirs(os.path.dirname(os.path.abspath(a.prefix)), exist_ok=True)
    for b, roots in enumerate(batches):
        out, tl = [], []
        for r in roots:
            out.append(f"\n### SCENE {r}"); render(r, "Opening", out)
        for line in out:
            m = re.match(r"\*\[([^\]]+)\]", line)
            if m: tl.append(m.group(1))
        base = f"{a.prefix}_{b:02d}"
        open(base + ".ctx.txt", "w", encoding="utf-8").write("SYSTEM PROMPT\n=============\n" + SYSTEM + "\n\nSCENES\n======\n" + "\n".join(out) + "\n")
        open(base + ".targets.tsv", "w", encoding="utf-8").write("wav\tspeaker\n" + "".join(f"{w}\t{speaker(w)}\n" for w in tl))
        print(f"{base}.ctx.txt  {len(roots)} scenes  {len(tl)} target lines")


BANNED = re.compile(r"\b(sigh|sighs|sighing|(?<!under his )(?<!under her )(?<!under the )breath|breathes|breathing|inhale|exhale|laugh|laughs|laughing|chuckl\w*|cough\w*|gasp\w*|groan\w*|sobs?|sobbing|snort\w*)\b", re.I)   # "scoffing" as a tone is fine: Breeze drops non-verbal cues


def check(prefix):
    ok = True; seen = {}
    for t in sorted(glob.glob(prefix + "_*.targets.tsv")):
        base = t[: -len(".targets.tsv")]; want = [r["wav"] for r in tsv(t)]
        d = base + ".dir.tsv"
        if not os.path.exists(d): print(f"{os.path.basename(base)}: MISSING output"); ok = False; continue
        got = tsv(d); gw = [r["wav"].upper() for r in got]
        extra = set(gw) - set(want); lack = [w for w in want if w not in set(gw)]
        dup = len(gw) - len(set(gw)); bad = [r["wav"] for r in got if BANNED.search(r.get("instruction", ""))]
        short = [r["wav"] for r in got if len(r.get("instruction", "").split()) < 2]
        for r in got:
            seen.setdefault(r.get("instruction", ""), []).append(os.path.basename(base))
        status = "ok" if not (extra or lack or dup or bad or short) else "PROBLEM"
        if status != "ok": ok = False
        print(f"{os.path.basename(base)}: {len(got)}/{len(want)} {status}" + (f" missing={len(lack)}" if lack else "") + (f" extra={len(extra)}" if extra else "")
              + (f" dup={dup}" if dup else "") + (f" nonverbal={bad[:3]}" if bad else "") + (f" short={short[:3]}" if short else ""))
    cross = {k: v for k, v in seen.items() if len(set(v)) > 1 and len(k.split()) > 5}
    if cross: print(f"identical instructions across batches: {len(cross)} (e.g. {list(cross)[:2]})")
    print("ALL OK" if ok else "problems above")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--lines"); ap.add_argument("--prefix"); ap.add_argument("--max", type=int, default=150)
    ap.add_argument("--check")
    a = ap.parse_args()
    if a.check: check(a.check)
    else: build(a)
