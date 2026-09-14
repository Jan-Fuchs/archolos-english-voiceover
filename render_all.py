"""Render a line set with Breeze: anchor per speaker from refs/cast/, direction per line from one or more
direction TSVs (fallback: a per-tier default with the pace rule). Resumable; writes out/final/<WAV>.wav (24 kHz PCM
as delivered by the server) and work/render_log.tsv.

usage: python render_all.py --lines work/stage1_lines.tsv [--directions work/batches/stage1_*.dir.tsv ...]
                            [--seed-offset 0] [--only-missing] [--limit N]
"""
import argparse, glob, hashlib, json, os, sys, time, urllib.request
P = os.path.dirname(os.path.abspath(__file__)); BASE = "http://127.0.0.1:8080"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
GUIDANCE = 3.5
DEFAULT_DIR = {"quest": "Unhurried and grounded, dry, in character; quiet unless the line itself is urgent.",
               "filler": "Unhurried, level, matter-of-fact; a passing remark, not a performance."}


def tsv(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8")]
    return [dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])]


def seed_for(wav, offset):
    return (int(hashlib.md5(wav.upper().encode()).hexdigest()[:8], 16) % 2_000_000_000) + offset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", required=True); ap.add_argument("--directions", nargs="*", default=[])
    ap.add_argument("--seed-offset", type=int, default=0); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--redo", help="TSV with a 'wav' column: re-render only these (QA re-takes)")
    ap.add_argument("--out", default=os.path.join(P, "out", "final"), help="output folder (default out/final)")
    ap.add_argument("--overwrite", action="store_true", help="re-render even if the output exists")
    args = ap.parse_args()
    lines = tsv(args.lines)
    if args.redo:
        redo = {r["wav"].upper() for r in tsv(args.redo)}; lines = [l for l in lines if l["wav"].upper() in redo]
    if args.limit: lines = lines[: args.limit]
    directions = {}
    for pat in args.directions:
        for f in glob.glob(pat):
            for r in tsv(f): directions[r["wav"].upper()] = r["instruction"]
    cast = os.path.join(P, "refs", "cast"); prompt = {}
    for l in open(os.path.join(cast, "prompt_text"), encoding="utf-8"):
        if "|" in l: k, v = l.rstrip("\n").split("|", 1); prompt[k] = v
    outdir = args.out; os.makedirs(outdir, exist_ok=True)
    logp = os.path.join(P, "work", "render_log.tsv")
    if not os.path.exists(logp): open(logp, "w", encoding="utf-8").write("wav\tspeaker\tseed\tbytes\tsecs\tdirection_source\n")
    log = open(logp, "a", encoding="utf-8")
    n_ok = n_skip = n_err = 0; t0 = time.time(); missing_anchor = set()
    for i, l in enumerate(lines, 1):
        wav, spk, text = l["wav"], l["speaker"], l["text"]
        out = os.path.join(outdir, wav.upper()[:-4] + ".wav")
        if os.path.exists(out) and not args.redo and not args.overwrite:
            n_skip += 1; continue
        anchor = os.path.join(cast, spk + ".wav")
        if not os.path.exists(anchor):
            missing_anchor.add(spk); n_err += 1; continue
        instr = directions.get(wav.upper()); src = "llm" if instr else "default"
        if not instr: instr = DEFAULT_DIR.get(l.get("tier", "quest"), DEFAULT_DIR["quest"])
        body = {"model": "breeze", "input": text, "voice_ref": anchor, "reference_text": prompt.get(spk, ""),
                "seed": seed_for(wav, args.seed_offset), "options": {"instruction": instr, "guidance_scale": GUIDANCE}}
        req = urllib.request.Request(BASE + "/v1/audio/speech", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        t1 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=900) as r: audio = r.read()
        except Exception as e:
            n_err += 1; print(f"  ERROR {wav}: {getattr(e, 'code', '')} {getattr(e, 'reason', e)}"); continue
        open(out, "wb").write(audio); n_ok += 1
        log.write(f"{wav}\t{spk}\t{body['seed']}\t{len(audio)}\t{time.time()-t1:.1f}\t{src}\n"); log.flush()
        if n_ok % 50 == 0:
            el = time.time() - t0; print(f"  {n_ok} rendered, {n_skip} skipped, {n_err} errors | {el/max(n_ok,1):.1f} s/line | {i}/{len(lines)} | {el/60:.0f} min")
    print(f"done: {n_ok} rendered, {n_skip} skipped, {n_err} errors in {(time.time()-t0)/60:.0f} min")
    if missing_anchor: print("missing anchors:", sorted(missing_anchor)[:20], "..." if len(missing_anchor) > 20 else "")


if __name__ == "__main__":
    main()
