r"""Install rendered lines into the game's loose-file tree, ready for pack_mod.py:
converts out/final/<WAV>.wav to 44.1 kHz mono into <game>\_work\Data\Sound\Speech\<WAV> (16-bit PCM, or 4-bit IMA ADPCM
with --adpcm: the format of the game's own speech files, a quarter of the size; use it for a release build).
Keeps an inventory (work/installed.txt) so --uninstall removes exactly what was installed.
Paths: ARCHOLOS_DIR (game folder) and FFMPEG (ffmpeg binary) environment variables, defaults below.
usage: python install_stage.py --lines work/stage1_lines.tsv [--skip-flagged] [--adpcm] | --uninstall
"""
import argparse, os, subprocess, sys
P = os.path.dirname(os.path.abspath(__file__))
GAME = os.environ.get("ARCHOLOS_DIR", r"C:\Program Files (x86)\Steam\steamapps\common\TheChroniclesOfMyrtana")
SPEECH = os.path.join(GAME, "_work", "Data", "Sound", "Speech")
FF = os.environ.get("FFMPEG", "ffmpeg")                       # any ffmpeg on PATH, or set FFMPEG to the full path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
INV = os.path.join(P, "work", "installed.txt")


def tsv(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8")]
    return [dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--lines"); ap.add_argument("--skip-flagged", action="store_true"); ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--adpcm", action="store_true", help="4-bit IMA ADPCM like the game's own speech files (a quarter of 16-bit PCM); use for a release build")
    args = ap.parse_args()
    codec = "adpcm_ima_wav" if args.adpcm else "pcm_s16le"
    if args.uninstall:
        n = 0
        if os.path.exists(INV):
            for l in open(INV, encoding="utf-8"):
                p = l.strip()
                if p and os.path.exists(p): os.remove(p); n += 1
            os.remove(INV)
        print(f"uninstalled {n} files from {SPEECH}"); return
    os.makedirs(SPEECH, exist_ok=True)
    flagged = set()
    if args.skip_flagged and os.path.exists(os.path.join(P, "work", "qa_flags.tsv")):
        flagged = {r["wav"].upper() for r in tsv(os.path.join(P, "work", "qa_flags.tsv"))}
    installed = set(l.strip() for l in open(INV, encoding="utf-8")) if os.path.exists(INV) else set()
    inv = open(INV, "a", encoding="utf-8"); n = skipped = 0
    for l in tsv(args.lines):
        wav = l["wav"].upper(); src = os.path.join(P, "out", "final", wav[:-4] + ".wav"); dst = os.path.join(SPEECH, wav)
        if not os.path.exists(src) or wav in flagged: skipped += 1; continue
        r = subprocess.run([FF, "-v", "error", "-y", "-i", src, "-ar", "44100", "-ac", "1", "-c:a", codec, dst], capture_output=True)
        if r.returncode != 0: print("  ffmpeg failed:", wav); continue
        if dst not in installed: inv.write(dst + "\n"); installed.add(dst)
        n += 1
    inv.close(); print(f"installed {n} lines into {SPEECH} ({skipped} skipped: not rendered or flagged)")


if __name__ == "__main__":
    main()
