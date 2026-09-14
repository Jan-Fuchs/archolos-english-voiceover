"""Build a self-contained blind listening page from generated clips.
Rows come from out/ab*/ folders (per-line A/B) and/or a casting folder (one line, several voices).
Audio is embedded as base64 MP3 so the page is one file.

usage:
  python make_ab_page.py --round r3 --intro "..." [--no-lines] [--lines work/test_lines_8.tsv]
                         [--casting out/marvin_design --casting-text "..." --casting-labels labels.json]
"""
import os, sys, glob, json, base64, subprocess, random, argparse
P = os.path.dirname(os.path.abspath(__file__))
FF = os.environ.get("FFMPEG", "ffmpeg")                       # ffmpeg on PATH, or FFMPEG=<full path>

VERSIONS = [("pack", "out/ab_packref/{n}_{s}_pack.wav", "StoneEyedJax pack"),
            ("breeze_packref", "out/ab_packref/{n}_{s}_breeze.wav", "Breeze · pack voice + direction"),
            ("higgs_packref", "out/ab_packref/{n}_{s}_higgs.wav", "Higgs · pack voice, clone only"),
            ("breeze", "out/ab/{n}_{s}_breeze.wav", "Breeze · Polish anchor + direction"),
            ("higgs", "out/ab/{n}_{s}_higgs.wav", "Higgs · Polish anchor, clone only"),
            ("breeze_hand", "out/ab_r3hand/{n}_{s}_breeze.wav", "Breeze · hand-written direction"),
            ("breeze_llm", "out/ab_r3llm/{n}_{s}_breeze.wav", "Breeze · Fable 5.1 direction"),
            ("breeze_opus5", "out/ab_r3opus5/{n}_{s}_breeze.wav", "Breeze · Opus 5 direction"),
            ("breeze_opus46", "out/ab_r3opus46/{n}_{s}_breeze.wav", "Breeze · Opus 4.6 direction"),
            ("breeze_sonnet5", "out/ab_r3sonnet5/{n}_{s}_breeze.wav", "Breeze · Sonnet 5 direction"),
            ("accent_plain", "out/ab_accent/{n}_{s}_plain.wav", "Polish anchor · plain direction"),
            ("accent_pinned", "out/ab_accent/{n}_{s}_pinned.wav", "Polish anchor · accent pinned in the direction"),
            ("accent_design", "out/ab_accent/{n}_{s}_design.wav", "Designed anchor · voice described from the Polish clip, no cloning"),
            ("de_cosy", "out/ab_de/{n}_{s}_cosyvoice3.wav", "Deutsch · CosyVoice3, gleiche Stimmen, mit Regieanweisung"),
            ("de_cosy_plain", "out/ab_de_plain/{n}_{s}_cosyvoice3.wav", "Deutsch · CosyVoice3, nur geklont, ohne Regie"),
            ("de_qwen", "out/ab_de/{n}_{s}_qwen3-tts.wav", "Deutsch · Qwen3-TTS, nur geklont")]


def tsv(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8")]
    return [dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])]


def mp3_b64(wav):
    r = subprocess.run([FF, "-v", "error", "-i", wav, "-af", "loudnorm=I=-18:TP=-2", "-ac", "1", "-ar", "24000",
                        "-c:a", "libmp3lame", "-b:a", "48k", "-f", "mp3", "pipe:1"], capture_output=True, check=True)
    return "data:audio/mpeg;base64," + base64.b64encode(r.stdout).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(P, "out", "ab_page.html"))
    ap.add_argument("--round", default="r1", help="round id; changing it resets all stored scores")
    ap.add_argument("--intro", default="")
    ap.add_argument("--lines", default=os.environ.get("LINES_FILE", os.path.join(P, "work", "test_lines.tsv")))
    ap.add_argument("--no-lines", action="store_true", help="omit the per-line ledger")
    ap.add_argument("--only", default="", help="comma-separated version keys to include (default: all present)")
    ap.add_argument("--casting", action="append", default=[], help="folder of wavs: one line, several voices (repeatable)")
    ap.add_argument("--casting-text", action="append", default=[])
    ap.add_argument("--casting-labels", action="append", default=[], help="JSON file {stem: label} (one per --casting)")
    args = ap.parse_args()

    random.seed(42)
    rows = []
    for ci, folder in enumerate(args.casting):
        lab = args.casting_labels[ci] if ci < len(args.casting_labels) else ""
        labels = json.load(open(lab, encoding="utf-8")) if lab else {}
        clips = []
        for w in sorted(glob.glob(os.path.join(folder, "*.wav"))):
            stem = os.path.splitext(os.path.basename(w))[0]
            clips.append({"key": stem, "label": labels.get(stem, stem), "src": mp3_b64(w)})
        random.shuffle(clips)
        who = os.path.basename(folder.rstrip("/\\")).split("_")[0].upper()
        rows.append({"n": ci, "speaker": who, "wav": "casting_" + os.path.basename(folder.rstrip("/\\")),
                     "text": args.casting_text[ci] if ci < len(args.casting_text) else "",
                     "direction": "Same line, different designed voices — which one would you want for all of this character's lines?", "clips": clips})
    if not args.no_lines:
        only = set(args.only.split(",")) if args.only else None
        directions = {r["wav"]: r["instruction"] for r in tsv(os.path.join(P, "work", "directions.tsv"))}
        for i, l in enumerate(tsv(args.lines), 1):
            clips = []
            for key, pat, label in VERSIONS:
                if only and key not in only:
                    continue
                p = os.path.join(P, pat.format(n=f"{i:02d}", s=l["speaker"]))
                if os.path.exists(p):
                    clips.append({"key": key, "label": label, "src": mp3_b64(p)})
            if len(clips) < 2:
                continue
            random.shuffle(clips)
            rows.append({"n": i, "speaker": l["speaker"], "wav": l["wav"], "text": l["text"],
                         "direction": directions.get(l["wav"], ""), "clips": clips})
    present = sorted({c["label"] for r in rows for c in r["clips"]})
    tpl = open(os.path.join(P, "ab_page_template.html"), encoding="utf-8").read()
    data = {"rows": rows, "versions": present, "round": args.round, "intro": args.intro}
    open(args.out, "w", encoding="utf-8").write(tpl.replace("/*__DATA__*/", "const DATA=" + json.dumps(data) + ";"))
    print(f"round {args.round}: {len(rows)} rows, versions: {present} -> {args.out} ({os.path.getsize(args.out)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
