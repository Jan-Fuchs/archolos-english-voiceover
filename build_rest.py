"""Line sets for everything not yet installed (chapters 2-6 + leftovers), split into render blocks by chapter.
Speaker per line: work/speaker_script.tsv (who_speaks.py), '?<instance>' resolved from the instance name, aliases for
chapter variants (same NPC instance under another token), MARVIN for _15_ lines. Lines whose speaker has no voice are
left to the original pack and listed in work/rest_unvoiced.tsv. Stage notes ("<orc sounds>") and grunts are skipped.
Chapter = quest token in the file name (Q2xx, SQ3xx, KQ4xx, PQ, CHAPTER4), else the first chapter the owner has a quest
line in, else 'world' (traders, guards, ambient NPCs). Block order: 1 (leftovers), 2, world, 3, 4, 5, 6.

output: work/rest_lines.tsv (all), work/rest_<block>_lines.tsv per block
"""
import collections, os, re
P = os.path.dirname(os.path.abspath(__file__)); os.chdir(P)
ALIAS = {"CAPTAINARCHOLOS": "CAPTAIN", "BORRIS": "BORIS"}
GRUNT = re.compile(r"^[^A-Za-z]*(a+r+g+h*|a+h+|u+g+h+|o+h+|h+m+|argh|ugh|hmpf|hm+|pff+|ouch|ow|oof|ah|oh|ha+|he+h*)[^A-Za-z]*\.*$", re.I)
TOK = re.compile(r"_(?:Q|SQ|KQ|PQ)(\d)\d\d(?=_|\.|$)|CHAPTER(\d)")
ORDER = ["1", "2", "world", "3", "4", "5", "6"]


def tsv(p):
    L = open(p, encoding="utf-8").read().splitlines(); h = L[0].split("\t"); return [dict(zip(h, l.split("\t"))) for l in L[1:]]


def main():
    ou = [r for r in tsv("work/ou_lines.tsv") if r["wav"].upper().endswith(".WAV") and not r["wav"].upper().startswith("SVM_")]
    ss = {r["wav"].upper(): r for r in tsv("work/speaker_script.tsv")}
    inst = {os.path.basename(l.strip()).upper() for l in open("work/installed.txt", encoding="utf-8") if l.strip()} if os.path.exists("work/installed.txt") else set()
    voiced = {f[:-4].upper() for f in os.listdir("refs/cast") if f.endswith(".wav")}
    by_inst = collections.defaultdict(collections.Counter)            # instance -> tokens that have a voice
    for r in ss.values():
        if r["speaker"] in voiced: by_inst[r["npc_instance"]][r["speaker"]] += 1
    def resolve(w):
        r = ss.get(w)
        if re.search(r"_15_\d+(_[A-Z])?\.WAV$", w) and (not r or r["speaker"] in ("MARVIN", "") or r["speaker"].startswith("?")): return "MARVIN"
        s = r["speaker"] if r else ""
        inst_name = r["npc_instance"] if r else ""
        s = ALIAS.get(s, s)
        if s in voiced: return s
        if inst_name and by_inst.get(inst_name): return by_inst[inst_name].most_common(1)[0][0]
        stem = re.sub(r"^\??[A-Z]+_\d+_", "", inst_name.lstrip("?")) if inst_name else ""
        for c in (stem, stem.split("_")[-1] if stem else "", re.sub(r"_(Q\d{3}|VZ|V\d)$", "", stem)):
            if c and c in voiced: return c
        m = re.match(r"(?:DIA|TRIA)_([^_]+)_", w)
        if m and not r and m.group(1) in voiced: return m.group(1)
        return None
    owner = lambda w: (re.match(r"(?:DIA|TRIA)_([^_]+)_", w) or [None, None])[1]
    first = collections.defaultdict(lambda: 99)
    for r in ou:
        w = r["wav"].upper(); m = TOK.search(w)
        if m:
            c = int(m.group(1) or m.group(2))
            for s in (ss.get(w, {}).get("speaker"), owner(w)):
                if c > 0 and s and s != "MARVIN": first[s] = min(first[s], c)
    rows, unvoiced, skipped = [], [], 0
    for r in ou:
        w = r["wav"].upper()
        if w in inst: continue
        t = r["text"].strip()
        if not t or re.search(r"<[^>]+>", t) or GRUNT.match(t): skipped += 1; continue
        spk = resolve(w)
        if not spk: unvoiced.append((w, ss.get(w, {}).get("speaker", ""), t)); continue
        m = TOK.search(w)
        if m and int(m.group(1) or m.group(2)) > 0: ch = str(int(m.group(1) or m.group(2)))
        else:
            o = owner(w); f = min(first[o], first[spk]) if o else first[spk]
            ch = str(f) if f < 99 else "world"
        tier = "quest" if m else "filler"
        rows.append((ch, spk, w, t, r["block"], tier))
    rows.sort(key=lambda x: ORDER.index(x[0]))
    hdr = "speaker\twav\ttext\tblock\ttier\tchapter\n"
    with open("work/rest_lines.tsv", "w", encoding="utf-8") as f:
        f.write(hdr); [f.write(f"{s}\t{w}\t{t}\t{b}\t{tr}\t{c}\n") for c, s, w, t, b, tr in rows]
    for blk in ORDER:
        sel = [x for x in rows if x[0] == blk]
        with open(f"work/rest_{blk}_lines.tsv", "w", encoding="utf-8") as f:
            f.write(hdr); [f.write(f"{s}\t{w}\t{t}\t{b}\t{tr}\t{c}\n") for c, s, w, t, b, tr in sel]
        print(f"block {blk:5s}: {len(sel):6d} lines, {len({x[1] for x in sel}):4d} speakers")
    with open("work/rest_unvoiced.tsv", "w", encoding="utf-8") as f:
        f.write("wav\tscript_speaker\ttext\n"); [f.write("\t".join(u) + "\n") for u in unvoiced]
    print(f"total {len(rows)} lines; {len(unvoiced)} left to the pack (no voice), {skipped} stage notes/grunts skipped")


if __name__ == "__main__":
    main()
