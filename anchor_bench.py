"""Expressiveness bench for one character. Measured on chapter 1: how much the anchor clip's pitch moves predicts how
much every rendered line moves (r = 0.86 over 58 speakers) - Breeze copies the reference clip's melody, so a flat
anchor gives a flat, "AI-sounding" character. This builds two alternatives and renders the same lines with each:
  livelier  same voice: the current anchor re-reads its own line with a lively instruction; the take with the most
            pitch movement that still matches the voice (ECAPA >= 0.7 to the old anchor) becomes the candidate anchor
  design    a new voice designed for expressiveness: the most expressive candidate that is heard as the right gender
            and stays distinct from the cast (ECAPA < 0.55)
and writes a blind page (current / livelier / design) per line. Apply a winner with recast_apply.py SPK=<wav>.
usage: .venv-audit\\Scripts\\python anchor_bench.py JORN --lines W1,W2,... [--design "<description>"] [--round jorn2]
"""
import argparse, glob, json, os, random, sys, urllib.request
import numpy as np, torch
P = os.path.dirname(os.path.abspath(__file__)); os.chdir(P); sys.path.insert(0, P)
from audit_audio import load, signal_stats, tsv
from cast_all import GENDER
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
LIVELY = "Warm and lively, a real person remembering and telling it; natural rising and falling intonation, feeling in the voice, unhurried."


def speech(body):
    req = urllib.request.Request("http://127.0.0.1:8080/v1/audio/speech", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r: return r.read()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("spk"); ap.add_argument("--lines", required=True); ap.add_argument("--design", default="")
    ap.add_argument("--round", default=""); ap.add_argument("--seeds", type=int, default=6)
    a = ap.parse_args(); torch.set_num_threads(4); spk = a.spk.upper(); g = GENDER.get(spk, "man")
    od = os.path.join("out", f"{spk.lower()}_bench"); os.makedirs(od, exist_ok=True)
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
    enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", savedir="models/audit/ecapa", run_opts={"device": "cpu"}, local_strategy=LocalStrategy.COPY)
    gname = "alefiury/wav2vec2-large-xlsr-53-gender-recognition-librispeech"
    gfe = AutoFeatureExtractor.from_pretrained(gname); gm = AutoModelForAudioClassification.from_pretrained(gname).eval()
    fem = {v.lower(): k for k, v in gm.config.id2label.items()}["female"]
    def emb(x):
        with torch.no_grad(): e = enc.encode_batch(torch.from_numpy(x)[None]).squeeze().numpy()
        return e / np.linalg.norm(e)
    prompt = {}
    for l in open("refs/cast/prompt_text", encoding="utf-8"):
        if "|" in l: k, v = l.rstrip("\n").split("|", 1); prompt[k] = v
    cur = f"refs/cast/{spk}.wav"; xc = load(cur)[0]; ec = emb(xc); print(f"current anchor pitch movement {signal_stats(xc)['f0_st_sd']:.2f} st")
    names = open("work/anchor_ecapa.txt").read().split("\n"); E = np.load("work/anchor_ecapa.npy")
    others = np.array([E[i] for i, n in enumerate(names) if n != spk])
    # 1. same voice, livelier anchor
    best = None
    for sd in range(1, a.seeds + 1):
        p = os.path.join(od, f"livelier_seed{sd}.wav")
        if not os.path.exists(p):
            open(p, "wb").write(speech({"model": "breeze", "input": prompt[spk], "voice_ref": os.path.abspath(cur), "reference_text": prompt[spk],
                                        "seed": sd, "options": {"instruction": LIVELY, "guidance_scale": 3.5}}))
        x = load(p)[0]; mv = signal_stats(x)["f0_st_sd"]; sim = float(emb(x) @ ec)
        print(f"  livelier seed {sd}: movement {mv:.2f} st, same-voice {sim:.2f}", flush=True)
        if sim >= 0.7 and (best is None or mv > best[0]): best = (mv, p)
    liv = best[1] if best else None
    # 2. new expressive design
    desc = a.design or json.load(open("work/cast_features.json", encoding="utf-8")).get(spk, {}) and ""
    if not desc:
        row = next(r for r in tsv("work/cast.tsv") if r["speaker"] == spk)
        desc = row["description"].split(" [")[0].replace("smooth and clear", "slightly rough").replace("Grounded and natural, not theatrical.", "Expressive, lively intonation that rises and falls naturally; grounded, a real person talking, not a narrator.")
    cands = []
    for sd in (7, 11, 23, 31, 41, 53)[: a.seeds]:
        p = os.path.join(od, f"design_seed{sd}.wav")
        if not os.path.exists(p): open(p, "wb").write(speech({"model": "breeze", "input": prompt[spk], "seed": sd, "options": {"instruction": desc, "guidance_scale": 3.5}}))
        x = load(p)[0]; mv = signal_stats(x)["f0_st_sd"]; e = emb(x); ms = float((others @ e).max())
        with torch.no_grad(): pf = float(gm(**gfe(x, sampling_rate=16000, return_tensors="pt")).logits.softmax(-1)[0][fem])
        ok = (pf > 0.9) if g == "woman" else (pf < 0.1)
        print(f"  design seed {sd}: movement {mv:.2f} st, max_sim {ms:.2f}, p_female {pf:.3f} {'OK' if ok else 'wrong gender'}", flush=True)
        near = [n for n in names if n != spk][int(np.argmax(others @ e))]
        cands.append((ok, ms < 0.55, mv, p, near, ms))
    pool = [c for c in cands if c[0] and c[1]] or [c for c in cands if c[0]]     # distinct if possible, else just the right gender
    best = max(pool, key=lambda c: c[2]) if pool else None
    if best and not best[1]: print(f"  no distinct design; most expressive one resembles {best[4]} ({best[5]:.2f})")
    des = best[3] if best else None
    json.dump({"design_description": desc, "livelier": liv, "design": des}, open(os.path.join(od, "picks.json"), "w"), indent=1)
    print("picks:", liv, des)
    # 3. render the bench lines with each anchor
    dirs = {}
    for f in glob.glob("work/batches/*.dir.tsv"):
        for r in tsv(f): dirs[r["wav"].upper()] = r["instruction"]
    text = {r["wav"].upper(): r["text"] for r in tsv("work/ou_lines.tsv")}
    variants = {"current": (cur, prompt[spk]), "livelier": (liv, prompt[spk]), "design": (des, prompt[spk])}
    from make_ab_page import mp3_b64
    rows = []
    for i, w in enumerate([w.strip().upper() for w in a.lines.split(",")], 1):
        clips = []
        for k, (anc, rt) in variants.items():
            if not anc: continue
            p = os.path.join(od, f"{k}_{w[:-4]}.wav")
            if not os.path.exists(p):
                open(p, "wb").write(speech({"model": "breeze", "input": text[w], "voice_ref": os.path.abspath(anc), "reference_text": rt,
                                            "seed": 1000 + i, "options": {"instruction": dirs.get(w, ""), "guidance_scale": 3.5}}))
            clips.append({"key": k, "label": {"current": f"current {spk.title()}", "livelier": "same voice, livelier anchor", "design": "new voice, designed for expression"}[k], "src": mp3_b64(p)})
        random.Random(i).shuffle(clips)
        rows.append({"n": i, "speaker": spk, "wav": w, "text": text[w], "direction": dirs.get(w, ""), "clips": clips})
    tpl = open("ab_page_template.html", encoding="utf-8").read()
    intro = (f"{spk.title()}: same lines, three versions, blind. One is the {spk.title()} you hear in the game now. Score how much each sounds like a real person "
             f"rather than an AI read-out, and which you'd want for all his lines.")
    data = {"rows": rows, "versions": sorted({c["label"] for r in rows for c in r["clips"]}), "round": a.round or f"{spk.lower()}_bench", "intro": intro}
    out = os.path.join("out", f"{spk.lower()}_bench.html")
    open(out, "w", encoding="utf-8").write(tpl.replace("/*__DATA__*/", "const DATA=" + json.dumps(data) + ";"))
    print("page ->", out)


if __name__ == "__main__":
    main()
