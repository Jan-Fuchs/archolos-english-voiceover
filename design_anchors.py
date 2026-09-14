"""Describe-then-design casting: turn each Polish anchor into a short acoustic description, have Breeze design a
native-English voice from it, and use that designed clip as the speaker's anchor. Then render the accent-audit
line for each speaker with the designed anchor so it can be compared against the Polish-anchor takes.

Descriptions are RELATIVE to the cast being processed (tercile bins), so voices differentiate from each other.
usage: python design_anchors.py            (uses refs/voices_accent/*.wav + work/accent_lines.tsv)
"""
import json, os, re, subprocess, sys, urllib.request
import numpy as np
P = os.path.dirname(os.path.abspath(__file__)); BASE = "http://127.0.0.1:8080"
FF = os.environ.get("FFMPEG", "ffmpeg")                       # ffmpeg on PATH, or FFMPEG=<full path>
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SR = 16000
PLAIN = "Level and unhurried, matter-of-fact, quiet."


def pcm(path):
    r = subprocess.run([FF, "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "s16le", "pipe:1"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def features(x):
    """Median F0 (octave-corrected), jitter (roughness proxy), spectral centroid (brightness), syllable-rate proxy."""
    frame, hop = int(0.04 * SR), int(0.01 * SR)
    f0s, cents, energies = [], [], []
    lo, hi = int(SR / 350), int(SR / 70)                       # 70-350 Hz search range
    for s in range(0, len(x) - frame, hop):
        w = x[s:s + frame]
        e = float(np.sqrt(np.mean(w * w))); energies.append(e)
        if e < 0.02:
            continue
        w = w - w.mean()
        ac = np.correlate(w, w, mode="full")[frame - 1:]
        ac = ac / (ac[0] + 1e-9)
        seg = ac[lo:hi]; k = int(np.argmax(seg)) + lo
        if seg.max() > 0.45:
            if 2 * k < hi and ac[2 * k] > 0.8 * ac[k]:        # strong peak at double the lag -> we picked a harmonic; use the true period
                k = 2 * k
            f0s.append(SR / k)
        spec = np.abs(np.fft.rfft(w * np.hanning(frame)))
        freqs = np.fft.rfftfreq(frame, 1 / SR)
        cents.append(float((spec * freqs).sum() / (spec.sum() + 1e-9)))
    f0s = np.array(f0s); en = np.array(energies)
    env = np.convolve(en, np.ones(5) / 5, mode="same"); thr = env.mean()
    peaks = sum(1 for i in range(1, len(env) - 1) if env[i] > thr and env[i] >= env[i - 1] and env[i] > env[i + 1])
    speech_sec = (en > 0.02).sum() * hop / SR
    return {"f0": float(np.median(f0s)) if len(f0s) else 0.0,
            "jitter": float(np.median(np.abs(np.diff(f0s)) / (f0s[:-1] + 1e-9))) if len(f0s) > 5 else 0.0,
            "centroid": float(np.median(cents)) if cents else 0.0,
            "rate": peaks / max(speech_sec, 0.5)}


def tercile(values):
    a = np.array(values); lo, hi = np.percentile(a, 33.3), np.percentile(a, 66.7)
    return lambda v: 0 if v <= lo else 1 if v <= hi else 2


def describe(ft, bins):
    f0 = ft["f0"]
    if f0 > 160:
        gender, pitch = "woman", ("high-pitched" if f0 > 230 else "mid-range" if f0 > 190 else "low for a woman")
    else:
        gender, pitch = "man", ("very deep" if f0 < 105 else "deep" if f0 < 125 else "low-medium" if f0 < 145 else "medium-pitched")
    grain = ["smooth and clear", "slightly rough", "gravelly, rough-edged"][bins["jitter"](ft["jitter"])]
    tone = ["dark, chesty", "warm", "bright, forward"][bins["centroid"](ft["centroid"])]
    pace = ["slowly", "at a measured pace", "briskly"][bins["rate"](ft["rate"])]
    return (f"Native English speaker, neutral accent, no regional or foreign accent. "
            f"Voice: a {gender}, {pitch}, {grain}, {tone} tone, speaks {pace}. Grounded and natural, not theatrical.")


def post(path, body, timeout=900):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main():
    rows = [l.rstrip("\n").split("\t") for l in open(os.path.join(P, "work", "accent_lines.tsv"), encoding="utf-8")][1:]
    text = {}
    for l in open(os.path.join(P, "work", "ou_lines.tsv"), encoding="utf-8"):
        r = l.rstrip("\n").split("\t")
        if len(r) >= 3 and r[1].upper().endswith(".WAV"):
            text[r[1].upper()] = r[2]
    vdir = os.path.join(P, "refs", "voices_design"); os.makedirs(vdir, exist_ok=True)
    outdir = os.path.join(P, "out", "ab_accent"); prompt = {}
    # pass 1: features for the whole cast, so bins are relative
    feats = {spk: features(pcm(os.path.join(P, "refs", "voices_accent", spk + ".wav"))) for spk, _, _ in rows}
    bins = {k: tercile([f[k] for f in feats.values()]) for k in ("jitter", "centroid", "rate")}
    # pass 2: describe, design, render
    for i, (spk, wav, line) in enumerate(rows, 1):
        ft = feats[spk]; desc = describe(ft, bins)
        own = [(len(t.split()), w, t) for w, t in text.items() if w.startswith(f"DIA_{spk}_") and not re.search(r"_15_\d+\.WAV$", w) and w != wav.upper() and 12 <= len(t.split()) <= 30]
        design_text = max(own)[2] if own else line
        audio = post("/v1/audio/speech", {"model": "breeze", "input": design_text, "seed": 7, "options": {"instruction": desc, "guidance_scale": 3.5}})
        anchor = os.path.join(vdir, spk + ".wav"); open(anchor, "wb").write(audio); prompt[spk] = design_text
        take = post("/v1/audio/speech", {"model": "breeze", "input": line, "voice_ref": anchor, "reference_text": design_text, "seed": 1234,
                                         "options": {"instruction": PLAIN, "guidance_scale": 3.5}})
        open(os.path.join(outdir, f"{i:02d}_{spk}_design.wav"), "wb").write(take)
        print(f"  {i:2} {spk:8} f0={ft['f0']:5.0f}Hz jit={ft['jitter']:.3f} cen={ft['centroid']:5.0f} rate={ft['rate']:.1f} -> {desc[68:desc.index('. Grounded')]}")
    with open(os.path.join(vdir, "prompt_text"), "w", encoding="utf-8") as f:
        for k, v in prompt.items(): f.write(f"{k}|{v}\n")
    print("designed anchors ->", vdir)


if __name__ == "__main__":
    main()
