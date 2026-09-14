"""Tempo-consistent take selection. For a line set, render K takes per line (seed offsets 0..K-1) with the given
directions into <takes>/<WAV>_k.wav, measure each take's words/sec, then pick one take per line so that consecutive
lines of the same speaker in a conversation keep a steady tempo unless the direction itself asks for a change
(brisk/urgent/quick... vs slow/unhurried...). Picked takes are copied to <out>/<WAV>.wav; a log goes to <out>/picks.tsv.
usage: python consistency_pick.py --lines work/demo/ship_lines.tsv --directions work/demo/ship_v2.dir.tsv
                                  --takes out/demo_ship_v2_takes --out out/demo_ship_v2_pick [--k 3]
"""
import argparse, glob, os, re, shutil, statistics, struct, subprocess, sys
P = os.path.dirname(os.path.abspath(__file__)); PY = sys.executable
FAST = re.compile(r"\b(brisk|quick|fast|hurried|rapid|snapp|clipped|urgent|rushing|pressing)\w*", re.I)
SLOW = re.compile(r"\b(slow|unhurried|measured|deliberate|leisurely|drawn[- ]out|lingering|takes (his|her) time)\w*", re.I)

def tsv(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8")]
    return [dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])]

def wav_seconds(path):
    b = open(path, "rb").read(64); i = b.find(b"fmt "); rate = struct.unpack_from("<I", b, i + 16)[0]
    ch = struct.unpack_from("<H", b, i + 10)[0]; bits = struct.unpack_from("<H", b, i + 22)[0]
    j = b.find(b"data"); size = struct.unpack_from("<I", b, j + 4)[0] if j >= 0 else os.path.getsize(path) - 44
    return size / (rate * ch * bits / 8)

def label(d):
    f, s = bool(FAST.search(d)), bool(SLOW.search(d)); return "F" if f and not s else "S"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", required=True); ap.add_argument("--directions", required=True)
    ap.add_argument("--takes", required=True); ap.add_argument("--out", required=True); ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()
    lines = tsv(args.lines); dirs = {r["wav"].upper(): r["instruction"] for r in tsv(args.directions)}
    os.makedirs(args.takes, exist_ok=True); os.makedirs(args.out, exist_ok=True)
    # 1. render K takes (render_all.py handles anchors/prompts; --out per take index)
    for k in range(args.k):
        sub = os.path.join(args.takes, f"k{k}")
        subprocess.run([PY, os.path.join(P, "render_all.py"), "--lines", args.lines, "--directions", args.directions,
                        "--seed-offset", str(k), "--out", sub], check=True)
    # 2. measure
    rate = {}
    for l in lines:
        w = l["wav"].upper(); n = len(l["text"].split())
        rate[w] = [n / max(wav_seconds(os.path.join(args.takes, f"k{k}", w[:-4] + ".wav")), 0.1) for k in range(args.k)]
    # 3. pick: per conversation, walk lines in order; per speaker keep a running tempo target
    picks = {}; log = open(os.path.join(args.out, "picks.tsv"), "w", encoding="utf-8"); log.write("wav\tspeaker\tlabel\ttakes_wps\tpicked\ttarget\n")
    convs = {}
    for l in lines: convs.setdefault(l.get("conv", l["block"]), []).append(l)
    for cv, ls in convs.items():
        spk_rates = {}
        for l in ls:                       # speaker baseline = median of all S-take rates in this conversation
            if label(dirs.get(l["wav"].upper(), "")) == "S": spk_rates.setdefault(l["speaker"], []).extend(rate[l["wav"].upper()])
        base = {s: statistics.median(v) for s, v in spk_rates.items()}
        last = {}
        for l in ls:
            w = l["wav"].upper(); s = l["speaker"]; lab = label(dirs.get(w, "")); r = rate[w]
            b = base.get(s, statistics.median(r))
            target = (last.get(s, b) if lab == "S" else max(b * 1.3, last.get(s, b) * 1.15))   # S: stay near the previous line; F: clearly quicker
            k = min(range(len(r)), key=lambda i: abs(r[i] - target) / target)
            picks[w] = k; last[s] = r[k] if lab == "S" else b                                    # after a brisk line, drift back to baseline
            shutil.copy(os.path.join(args.takes, f"k{k}", w[:-4] + ".wav"), os.path.join(args.out, w[:-4] + ".wav"))
            log.write(f"{w}\t{s}\t{lab}\t{','.join(f'{x:.2f}' for x in r)}\t{k}\t{target:.2f}\n")
    log.close(); print(f"picked {len(picks)} takes -> {args.out}")

if __name__ == "__main__":
    main()
