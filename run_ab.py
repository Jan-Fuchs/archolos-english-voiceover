"""A/B driver: generate the 20 test lines with each model via the audio.cpp server,
cloning each speaker from refs/voices/<SPEAKER>.wav (Polish anchor) with the transcript
from refs/voices/prompt_text, steering delivery with work/directions.tsv.
usage: python run_ab.py [breeze] [higgs]   (default: both)"""
import json, os, sys, time, shutil, urllib.request
P = os.path.dirname(os.path.abspath(__file__)); BASE = "http://127.0.0.1:8080"
VOICES = os.environ.get("VOICES_DIR", os.path.join(P, "refs", "voices"))   # anchor wavs + prompt_text
TAG = os.environ.get("OUT_TAG", "")                                         # suffix for out dirs
SPEAKER_BASE = {   # fallback direction when a line has no entry in directions.tsv
    "MARVIN":   "Young man, calm and grounded, unhurried, dry.",
    "RODERICH": "Gruff older guard captain. Low voice, authoritative, slow.",
    "LORENZO":  "Smooth, confident merchant lord. Measured, slightly condescending.",
}
GUIDANCE = 3.5   # Breeze: how much the instruction overrides the clip (1 = ignore text direction)
def tsv(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8")]
    return [dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])]
lines = tsv(os.environ.get("LINES_FILE", os.path.join(P, "work", "test_lines.tsv")))
directions = {r["wav"]: r["instruction"] for r in tsv(os.environ.get("DIRECTIONS_FILE", os.path.join(P, "work", "directions.tsv")))}
prompt_text = {}
pt = os.path.join(VOICES, "prompt_text")
if os.path.exists(pt):
    for l in open(pt, encoding="utf-8"):
        if "|" in l: k, v = l.rstrip("\n").split("|", 1); prompt_text[k] = v
models = sys.argv[1:] or ["breeze", "higgs"]
for model in models:
    outdir = os.path.join(P, "out", model + TAG); os.makedirs(outdir, exist_ok=True)
    for i, l in enumerate(lines, 1):
        spk, wav, text = l["speaker"], l["wav"], l["text"]
        ref = os.path.join(VOICES, spk + ".wav")
        if not os.path.exists(ref): print(f"!! missing anchor {ref}"); break
        instr = directions.get(wav) or SPEAKER_BASE[spk]
        body = {"model": model, "input": text, "voice_ref": ref, "seed": 1234,
                "reference_text": prompt_text.get(spk, "")}
        if model == "breeze": body["options"] = {"instruction": instr, "guidance_scale": GUIDANCE}
        elif model.startswith("cosyvoice3"):   # instruct = clone + text direction; cross_lingual = clone only (any-language anchor)
            tpl = os.environ.get("COSY_TEMPLATE", "instruct")
            body["options"] = {"template_name": tpl, "reference_text": prompt_text.get(spk, "")}
            if tpl == "instruct": body["options"]["instruction"] = instr
        elif model.startswith("qwen3-tts"):    # Base = clone only; language hint for German text
            body["language"] = os.environ.get("TTS_LANG", "")
        # higgs: no instruction option in its spec
        req = urllib.request.Request(BASE + "/v1/audio/speech", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=600) as r: audio = r.read()
        except Exception as e:
            print(f"  {model} {i:2} {wav}: ERROR {getattr(e,'code','')} {getattr(e,'reason',e)}")
            try: print("     ", e.read()[:300])
            except Exception: pass
            continue
        out = os.path.join(outdir, wav[:-4] + ".wav"); open(out, "wb").write(audio)
        print(f"  {model} {i:2} {spk:8} {wav[:44]:44} {len(audio)/1e3:7.0f} KB {time.time()-t0:5.1f}s")
# side-by-side listening folder: NN_SPEAKER_<pack|model>.wav
ab = os.path.join(P, "out", "ab" + TAG); os.makedirs(ab, exist_ok=True)
for i, l in enumerate(lines, 1):
    stem = f"{i:02d}_{l['speaker']}"
    pack = os.path.join(P, "refs", "en_pack", l["wav"][:-4] + "_pcm.wav")
    if os.path.exists(pack): shutil.copy2(pack, os.path.join(ab, stem + "_pack.wav"))
    for m in models:
        g = os.path.join(P, "out", m + TAG, l["wav"][:-4] + ".wav")
        if os.path.exists(g): shutil.copy2(g, os.path.join(ab, f"{stem}_{m}.wav"))
print("listening set ->", ab)
