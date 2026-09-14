"""Cast every dialogue speaker by describe-then-design.
For each speaker: gather up to ~15 s of their Polish lines, extract pitch/roughness/brightness/pace, bin the
features relative to the whole cast, write a voice description (native English, ~20% with a light regional
flavour fixed per character), have Breeze design the voice speaking that character's own longest English line,
and store the clip as the speaker's anchor. Marvin is fixed to the chosen design J. Resumable.

output: refs/cast/<SPEAKER>.wav, refs/cast/prompt_text, work/cast.tsv
usage: python cast_all.py [--limit N] [--only SPK,SPK]
"""
import argparse, glob, hashlib, json, os, re, struct, subprocess, sys, time, urllib.request
import numpy as np
from design_anchors import features, SR
P = os.path.dirname(os.path.abspath(__file__)); BASE = "http://127.0.0.1:8080"
D = os.path.join(os.environ.get("ARCHOLOS_DIR", "C:/Program Files (x86)/Steam/steamapps/common/TheChroniclesOfMyrtana"), "Data")
FF = os.environ.get("FFMPEG", "ffmpeg")                       # ffmpeg on PATH, or FFMPEG=<full path>
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ACCENTS = ["a light Northern English accent", "a soft Scottish accent", "a mild Irish accent", "a West Country English accent", "a light Welsh accent"]
IS_HERO = re.compile(r"_15_\d+\.WAV$", re.I)
GENDER = {}
_gp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work", "gender_llm.tsv")
if os.path.exists(_gp):
    for _l in open(_gp, encoding="utf-8").read().splitlines()[1:]:
        _r = _l.split("	")
        if len(_r) >= 2: GENDER[_r[0].upper()] = _r[1].strip().lower()
SPK_RE = re.compile(r"^(?:DIA|TRIA)_([^_]+)_", re.I)


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


def decode_lines(cat, names):
    """Concatenate the given archive entries into one 16 kHz float array (via ffmpeg)."""
    chunks = []
    for n in names:
        p, off, sz = cat[n]; f = open(p, "rb"); f.seek(off); raw = f.read(sz)
        r = subprocess.run([FF, "-v", "error", "-f", "wav", "-i", "pipe:0", "-ac", "1", "-ar", str(SR), "-f", "s16le", "pipe:1"], input=raw, capture_output=True)
        if r.returncode == 0 and r.stdout:
            chunks.append(np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0)
    return np.concatenate(chunks) if chunks else np.zeros(SR, dtype=np.float32)


def tercile(values):
    a = np.array(values); lo, hi = np.percentile(a, 33.3), np.percentile(a, 66.7)
    return lambda v: 0 if v <= lo else 1 if v <= hi else 2


def describe(spk, ft, bins):
    f0 = ft["f0"]
    g = GENDER.get(spk)                                   # LLM-judged gender from name + lines, when available
    if (g == "woman") if g else (f0 > 160):
        gender, pitch = "woman", ("high-pitched" if f0 > 230 else "mid-range" if f0 > 190 else "low for a woman")
    else:
        gender, pitch = "man", ("very deep" if f0 < 105 else "deep" if f0 < 125 else "low-medium" if f0 < 145 else "medium-pitched" if f0 < 175 else "high for a man, tenor-like")
    grain = ["smooth and clear", "slightly rough", "gravelly, rough-edged"][bins["jitter"](ft["jitter"])]
    tone = ["dark, chesty", "warm", "bright, forward"][bins["centroid"](ft["centroid"])]
    pace = ["slowly", "at a measured pace", "briskly"][bins["rate"](ft["rate"])]
    h = int(hashlib.md5(spk.encode()).hexdigest(), 16)
    accent = ACCENTS[(h // 7) % len(ACCENTS)] if h % 5 == 0 else "neutral accent, no regional or foreign accent"   # selection and palette use different hash slices
    return accent, (f"Native English speaker, {accent}. Voice: a {gender}, {pitch}, {grain}, {tone} tone, speaks {pace}. Grounded and natural, not theatrical.")


def post(body, timeout=900):
    req = urllib.request.Request(BASE + "/v1/audio/speech", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--only", default="")
    args = ap.parse_args()
    pl = catalog("KM_Speech*PL.mod")
    text = {}
    for l in open(os.path.join(P, "work", "ou_lines.tsv"), encoding="utf-8"):
        r = l.rstrip("\n").split("\t")
        if len(r) >= 3 and r[1].upper().endswith(".WAV"):
            text[r[1].upper()] = r[2]
    by_spk = {}
    for n in pl:
        m = SPK_RE.match(n)
        if m and not IS_HERO.search(n):
            by_spk.setdefault(m.group(1).upper(), []).append(n)
    rate_cache = {}
    def dur(n):
        p, off, sz = pl[n]
        if p not in rate_cache: rate_cache[p] = byte_rate(p, off)
        return sz / rate_cache[p]
    order = sorted(by_spk, key=lambda s: -len(by_spk[s]))          # important speakers first
    if args.only: order = [s for s in args.only.upper().split(",") if s in by_spk]
    if args.limit: order = order[: args.limit]
    cdir = os.path.join(P, "refs", "cast"); os.makedirs(cdir, exist_ok=True)
    cast_path = os.path.join(P, "work", "cast.tsv"); prompt_path = os.path.join(cdir, "prompt_text")
    # Marvin is fixed to a hand-picked design when that file exists; on a fresh clone he is designed from his cast.tsv row like everyone else
    j = os.path.join(P, "out", "marvin_design2", "marvin_H_resonant.wav")
    if not os.path.exists(os.path.join(cdir, "MARVIN.wav")) and os.path.exists(j):
        open(os.path.join(cdir, "MARVIN.wav"), "wb").write(open(j, "rb").read())
    by_spk.setdefault("MARVIN", [n for n in pl if IS_HERO.search(n)][:200])
    prompt = {}
    if os.path.exists(prompt_path):
        for l in open(prompt_path, encoding="utf-8"):
            if "|" in l: k, v = l.rstrip("\n").split("|", 1); prompt[k] = v
    # pass 1: features for the whole cast (cached)
    feat_path = os.path.join(P, "work", "cast_features.json")
    feats = json.load(open(feat_path, encoding="utf-8")) if os.path.exists(feat_path) else {}
    t0 = time.time()
    for i, spk in enumerate(order, 1):
        if spk in feats: continue
        names, total = [], 0.0
        for n in sorted(by_spk[spk], key=dur, reverse=True):
            if dur(n) > 12: continue
            names.append(n); total += dur(n)
            if total >= 15: break
        if not names: names = by_spk[spk][:2]
        feats[spk] = features(decode_lines(pl, names)); feats[spk]["sec"] = round(total, 1); feats[spk]["lines"] = len(by_spk[spk])
        if i % 100 == 0:
            json.dump(feats, open(feat_path, "w", encoding="utf-8")); print(f"  features {i}/{len(order)}  {time.time()-t0:.0f}s")
    json.dump(feats, open(feat_path, "w", encoding="utf-8"))
    bins = {k: tercile([f[k] for f in feats.values()]) for k in ("jitter", "centroid", "rate")}
    print(f"features ready for {len(feats)} speakers ({time.time()-t0:.0f}s)")
    # pass 2: describe + design
    known = {}                                   # speakers already in cast.tsv keep their description: a fresh clone regenerates
    if os.path.exists(cast_path):                # the shipped cast (same descriptions, seed 7) instead of inventing a new one
        for l in open(cast_path, encoding="utf-8").read().splitlines()[1:]:
            r = l.split("\t")
            if len(r) >= 9: known[r[0]] = (r[7], r[8])
    else:
        open(cast_path, "w", encoding="utf-8").write("speaker\tlines\tsec\tf0\tjitter\tcentroid\trate\taccent\tdescription\tdesign_text\n")
    n_new = 0
    with open(cast_path, "a", encoding="utf-8") as cf, open(prompt_path, "w", encoding="utf-8") as pf:
        for k, v in prompt.items(): pf.write(f"{k}|{v}\n")
        for i, spk in enumerate(order, 1):
            if os.path.exists(os.path.join(cdir, spk + ".wav")):
                continue
            ft = feats.get(spk, {}); accent, desc = known[spk] if spk in known else describe(spk, ft, bins)
            own = [(len(text[n].split()), n) for n in by_spk[spk] if n in text and 12 <= len(text[n].split()) <= 30]
            design_text = text[max(own)[1]] if own else max((text[n] for n in by_spk[spk] if n in text), key=len, default="Very well. I will see to it myself.")
            try:
                audio = post({"model": "breeze", "input": design_text, "seed": 7, "options": {"instruction": desc, "guidance_scale": 3.5}})
            except Exception as e:
                print(f"  !! {spk}: {getattr(e, 'code', '')} {getattr(e, 'reason', e)}"); continue
            open(os.path.join(cdir, spk + ".wav"), "wb").write(audio)
            prompt[spk] = design_text; pf.write(f"{spk}|{design_text}\n"); pf.flush()
            if spk not in known:
                cf.write(f"{spk}\t{ft['lines']}\t{ft['sec']}\t{ft['f0']:.0f}\t{ft['jitter']:.3f}\t{ft['centroid']:.0f}\t{ft['rate']:.1f}\t{accent}\t{desc}\t{design_text}\n"); cf.flush()
            n_new += 1
            if n_new % 25 == 0: print(f"  designed {n_new} ({i}/{len(order)})  {time.time()-t0:.0f}s")
    print(f"cast complete: {n_new} new designs, {len(order)} speakers, {time.time()-t0:.0f}s -> {cdir}")


if __name__ == "__main__":
    main()
