r"""Install rendered lines into the game's loose-file tree, ready for pack_mod.py:
levels each out/final/<WAV>.wav to -20 dB RMS (peaks capped at -1 dBFS; NPC speech plays positionally, so quiet takes
vanish at a distance) and writes it as 44.1 kHz mono 4-bit IMA ADPCM, the format of the game's own speech files, to
<game>\_work\Data\Sound\Speech\<WAV>. Keeps an inventory (work/installed.txt) so --uninstall removes exactly what was installed.
Paths: ARCHOLOS_DIR (game folder) and FFMPEG (ffmpeg binary) environment variables, defaults below.
usage: python install_stage.py --lines work/stage1_lines.tsv [--skip-flagged] | --uninstall
"""
import argparse, os, subprocess, sys
import numpy as np
P = os.path.dirname(os.path.abspath(__file__))
GAME = os.environ.get("ARCHOLOS_DIR", r"C:\Program Files (x86)\Steam\steamapps\common\TheChroniclesOfMyrtana")
SPEECH = os.path.join(GAME, "_work", "Data", "Sound", "Speech")
FF = os.environ.get("FFMPEG", "ffmpeg")                       # any ffmpeg on PATH, or set FFMPEG to the full path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
INV = os.path.join(P, "work", "installed.txt")
TARGET_RMS, MAX_PEAK = -20.0, -1.0                            # dBFS; Polish originals sit near -18, the old English pack near -21


def tsv(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8")]
    return [dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])]


def gain_db(src):
    r = subprocess.run([FF, "-v", "error", "-i", src, "-f", "f32le", "-ac", "1", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, dtype=np.float32)
    if r.returncode or not len(x): return None
    rms = 20 * np.log10(np.sqrt((x.astype(np.float64) ** 2).mean()) + 1e-9); peak = 20 * np.log10(np.abs(x).max() + 1e-9)
    return float(np.clip(min(TARGET_RMS - rms, MAX_PEAK - peak), -12.0, 18.0))


def install(src, dst):
    g = gain_db(src)
    if g is None: return False
    r = subprocess.run([FF, "-v", "error", "-y", "-i", src, "-af", f"volume={g:.2f}dB", "-ar", "44100", "-ac", "1", "-c:a", "adpcm_ima_wav", dst],
                       capture_output=True)
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--lines"); ap.add_argument("--skip-flagged", action="store_true"); ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()
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
        if not install(src, dst): print("  ffmpeg failed:", wav); continue
        if dst not in installed: inv.write(dst + "\n"); installed.add(dst)
        n += 1
    inv.close(); print(f"installed {n} lines into {SPEECH} ({skipped} skipped: not rendered or flagged)")


if __name__ == "__main__":
    main()
