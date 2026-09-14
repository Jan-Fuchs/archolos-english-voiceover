"""Build per-speaker Polish reference anchors from the Polish Voice-Over Pack archives, then
transcribe them with qwen3-asr via the server to produce refs/voices/prompt_text.
usage: python make_anchors.py  [--no-asr]"""
import struct, os, sys, glob, json, subprocess, urllib.request, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Polish transcripts vs cp1252 console
P = os.path.dirname(os.path.abspath(__file__)); BASE = "http://127.0.0.1:8080"
D = os.path.join(os.environ.get("ARCHOLOS_DIR", "C:/Program Files (x86)/Steam/steamapps/common/TheChroniclesOfMyrtana"), "Data")
FF = os.environ.get("FFMPEG", "ffmpeg")                       # ffmpeg on PATH, or FFMPEG=<full path>
SPEAKERS = {"MARVIN": lambda n: re.search(r"_15_\d+\.WAV$", n), "RODERICH": lambda n: n.startswith("DIA_RODERICH_") and not re.search(r"_15_\d+\.WAV$", n),
            "LORENZO": lambda n: n.startswith("DIA_LORENZO_") and not re.search(r"_15_\d+\.WAV$", n)}
TARGET_SEC, MIN_SEC, MAX_SEC = 18.0, 3.0, 9.0
# --- catalog of the Polish archives
cat = {}
for p in sorted(glob.glob(os.path.join(D, "KM_Speech*PL.mod"))):
    if os.path.getsize(p) == 0: continue
    f = open(p, "rb"); f.seek(272); ne = struct.unpack("<I", f.read(4))[0]; f.seek(296)
    for _ in range(ne):
        e = f.read(80); typ = struct.unpack_from("<I", e, 72)[0]
        if not typ & 0x80000000: cat[e[:64].decode("latin-1").rstrip(" \x00").upper()] = (p,) + struct.unpack_from("<II", e, 64)
print(f"Polish archive entries: {len(cat)}")
if not cat: sys.exit("no Polish archives found in Data/")
def byte_rate(p, off):
    f = open(p, "rb"); f.seek(off); w = f.read(64); i = w.find(b"fmt "); return struct.unpack_from("<I", w, i + 16)[0] or 16000
vdir = os.path.join(P, "refs", "voices"); os.makedirs(vdir, exist_ok=True); os.makedirs(os.path.join(P, "refs", "pl_lines"), exist_ok=True)
prompt = {}
for spk, match in SPEAKERS.items():
    names = [n for n in cat if match(n)]
    br = byte_rate(*cat[names[0]][:2])
    cands = sorted(((cat[n][2] / br, n) for n in names), reverse=True)           # longest first
    cands = [(d, n) for d, n in cands if MIN_SEC <= d <= MAX_SEC][:40]
    picked, total = [], 0.0
    for d, n in cands[::3]:                                                     # spread across the list
        if total + d > TARGET_SEC: continue
        picked.append(n); total += d
        if total >= TARGET_SEC - 2: break
    parts = []
    for n in picked:
        p, off, sz = cat[n]; f = open(p, "rb"); f.seek(off); raw = f.read(sz)
        rp = os.path.join(P, "refs", "pl_lines", n); open(rp, "wb").write(raw)
        pp = rp[:-4] + "_pcm.wav"; subprocess.run([FF, "-v", "error", "-y", "-i", rp, "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", pp], check=True); parts.append(pp)
    lst = os.path.join(vdir, spk + "_concat.txt"); open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
    out = os.path.join(vdir, spk + ".wav")
    subprocess.run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-af", "apad=pad_dur=0.25,loudnorm=I=-18:TP=-2", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", out], check=True)
    print(f"{spk:9} {len(picked)} lines, ~{total:.1f}s -> {out}")
    if "--no-asr" in sys.argv: continue
    body = {"model": "qwen3-asr", "audio": out, "language": "pl"}     # JSON path: server-local file via "audio"
    req = urllib.request.Request(BASE + "/v1/audio/transcriptions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r: txt = json.load(r).get("text", "").strip()
    except Exception as e:
        txt = ""; print("  asr error:", getattr(e, "code", ""), getattr(e, "reason", e))
        try: print("   ", e.read()[:300])
        except Exception: pass
    prompt[spk] = txt; print(f"  transcript: {txt[:140]}")
if prompt:
    with open(os.path.join(vdir, "prompt_text"), "w", encoding="utf-8") as f:
        for k, v in prompt.items(): f.write(f"{k}|{v}\n")
    print("wrote", os.path.join(vdir, "prompt_text"))
