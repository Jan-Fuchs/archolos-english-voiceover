"""Accent audit for the auto-built Polish anchors.
Picks N random NPC speakers, builds their anchors exactly the way the full run would (Polish pack lines,
concatenated, ASR-transcribed), renders one English line per speaker with Breeze twice — plain direction
vs. direction with an explicit accent pin — and writes work/accent_lines.tsv + out/ab_accent/ for the bench.
usage: python accent_audit.py [--n 8] [--seed 3]"""
import argparse, glob, json, os, random, re, struct, subprocess, sys, urllib.request
P = os.path.dirname(os.path.abspath(__file__)); BASE = "http://127.0.0.1:8080"
D = os.path.join(os.environ.get("ARCHOLOS_DIR", "C:/Program Files (x86)/Steam/steamapps/common/TheChroniclesOfMyrtana"), "Data")
FF = os.environ.get("FFMPEG", "ffmpeg")                       # ffmpeg on PATH, or FFMPEG=<full path>
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ACC = "Native English speaker, neutral accent, no regional or foreign accent. "
PLAIN = "Level and unhurried, matter-of-fact, quiet."
EXCLUDE = {"RODERICH", "LORENZO"}


def catalog(pattern):
    cat = {}
    for p in sorted(glob.glob(os.path.join(D, pattern))):
        if os.path.getsize(p) == 0:
            continue
        f = open(p, "rb"); f.seek(272); ne = struct.unpack("<I", f.read(4))[0]; f.seek(296)
        for _ in range(ne):
            e = f.read(80); typ = struct.unpack_from("<I", e, 72)[0]
            if not typ & 0x80000000:
                cat[e[:64].decode("latin-1").rstrip(" \x00").upper()] = (p,) + struct.unpack_from("<II", e, 64)
    return cat


def byte_rate(p, off):
    f = open(p, "rb"); f.seek(off); w = f.read(64); i = w.find(b"fmt "); return struct.unpack_from("<I", w, i + 16)[0] or 16000


def post(path, body, timeout=900):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if path.endswith("/speech") else json.load(r)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=8); ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args(); random.seed(args.seed)
    pl = catalog("KM_Speech*PL.mod")
    text = {}
    for l in open(os.path.join(P, "work", "ou_lines.tsv"), encoding="utf-8"):
        r = l.rstrip("\n").split("\t")
        if len(r) >= 3 and r[1].upper().endswith(".WAV"):
            text[r[1].upper()] = r[2]
    # candidate speakers: NPC dialogue lines (not Marvin's _15_ replies), enough 3-9 s Polish lines to anchor from
    by_spk = {}
    for n in pl:
        m = re.match(r"DIA_([^_]+)_", n)
        if not m or re.search(r"_15_\d+\.WAV$", n) or n not in text:
            continue
        by_spk.setdefault(m.group(1), []).append(n)
    rate_cache = {}
    def dur(n):
        p, off, sz = pl[n]
        if p not in rate_cache: rate_cache[p] = byte_rate(p, off)
        return sz / rate_cache[p]
    eligible = []
    for spk, names in by_spk.items():
        if spk in EXCLUDE or spk.isdigit():
            continue
        good = [n for n in names if 3.0 <= dur(n) <= 9.0]
        if len(good) >= 6:
            eligible.append((spk, good))
    random.shuffle(eligible); chosen = eligible[: args.n]
    print(f"eligible speakers: {len(eligible)}; chosen: {[s for s, _ in chosen]}")
    vdir = os.path.join(P, "refs", "voices_accent"); os.makedirs(vdir, exist_ok=True)
    outdir = os.path.join(P, "out", "ab_accent"); os.makedirs(outdir, exist_ok=True)
    rows = []
    for i, (spk, good) in enumerate(chosen, 1):
        # --- anchor: three mid-length Polish lines, ~15 s, loudness-normalised
        picks, total, parts = [], 0.0, []
        for n in sorted(good, key=dur, reverse=True)[::2]:
            if total + dur(n) > 16: continue
            picks.append(n); total += dur(n)
            if total >= 12: break
        for n in picks:
            p, off, sz = pl[n]; f = open(p, "rb"); f.seek(off); raw = f.read(sz)
            rp = os.path.join(vdir, n); open(rp, "wb").write(raw); pp = rp[:-4] + "_pcm.wav"
            subprocess.run([FF, "-v", "error", "-y", "-i", rp, "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", pp], check=True); parts.append(pp)
        lst = os.path.join(vdir, spk + "_concat.txt"); open(lst, "w").write("".join(f"file '{x}'\n" for x in parts))
        anchor = os.path.join(vdir, spk + ".wav")
        subprocess.run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-af", "apad=pad_dur=0.25,loudnorm=I=-18:TP=-2", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", anchor], check=True)
        transcript = post("/v1/audio/transcriptions", {"model": "qwen3-asr", "audio": anchor, "language": "pl"}).get("text", "").strip()
        # --- one English line to render (8-20 words, not one of the anchor lines)
        line_pool = [n for n in good if n not in picks and 8 <= len(text[n].split()) <= 20] or [n for n in good if n not in picks]
        wav = random.choice(line_pool); line = text[wav]
        rows.append((spk, wav, line))
        for variant, instr in (("plain", PLAIN), ("pinned", ACC + PLAIN)):
            audio = post("/v1/audio/speech", {"model": "breeze", "input": line, "voice_ref": anchor, "reference_text": transcript, "seed": 1234,
                                              "options": {"instruction": instr, "guidance_scale": 3.5}})
            open(os.path.join(outdir, f"{i:02d}_{spk}_{variant}.wav"), "wb").write(audio)
        print(f"  {i:2} {spk:12} anchor {total:4.1f}s ({len(picks)} lines) | line: {line[:60]}")
    with open(os.path.join(P, "work", "accent_lines.tsv"), "w", encoding="utf-8") as f:
        f.write("speaker\twav\ttext\n")
        for spk, wav, line in rows: f.write(f"{spk}\t{wav}\t{line}\n")
    print("wrote work/accent_lines.tsv and", outdir)


if __name__ == "__main__":
    main()
