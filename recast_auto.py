"""Automatic recast with checks: for each speaker, rebuild the voice description from the Polish features with the
script gender (work/gender_llm.tsv, merged from GOTHIC.DAT), design N candidates (different seeds) speaking the anchor
line, and pick the candidate that (1) is heard as the right gender by a wav2vec2 gender classifier, (2) is distinct from every other anchor in the cast
(ECAPA cosine; different human actors in the Polish cast stay below ~0.5), (3) has a lively melody (pitch movement in
semitones; rendered lines inherit the anchor's, r = 0.86 on chapter 1), and (4) reasonable UTMOS22 as a tie-breaker. All candidates stay in out/recast_auto/<SPK>/ so a human can
override the pick with recast_apply.py.

Runs in .venv-audit (torch CPU, speechbrain, transformers) against the audio server (Breeze on the GPU).
usage: .venv-audit\\Scripts\\python recast_auto.py SPK1,SPK2 [--seeds 7,11,23,31,41,53] [--apply]
  --apply   install the pick as refs/cast/<SPK>.wav (old one kept as .bak-<time>), update work/cast.tsv and
            work/cast_overrides.tsv. Re-rendering the speaker's lines is a separate step.
"""
import argparse, glob, json, os, re, shutil, sys, time, urllib.request
import numpy as np, torch
P = os.path.dirname(os.path.abspath(__file__)); os.chdir(P); sys.path.insert(0, P)
from audit_audio import load, signal_stats, tsv
from cast_all import describe, tercile, GENDER
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8080"


def design(text, desc, seed):
    body = {"model": "breeze", "input": text, "seed": seed, "options": {"instruction": desc, "guidance_scale": 3.5}}
    req = urllib.request.Request(BASE + "/v1/audio/speech", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r: return r.read()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("speakers"); ap.add_argument("--seeds", default="7,11,23,31,41,53")
    ap.add_argument("--apply", action="store_true"); ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args(); torch.set_num_threads(a.threads)
    spks = [s.strip().upper() for s in a.speakers.split(",") if s.strip()]; seeds = [int(s) for s in a.seeds.split(",")]
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
    enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", savedir="models/audit/ecapa",
                                         run_opts={"device": "cpu"}, local_strategy=LocalStrategy.COPY)
    gname = "alefiury/wav2vec2-large-xlsr-53-gender-recognition-librispeech"
    gfe = AutoFeatureExtractor.from_pretrained(gname); gm = AutoModelForAudioClassification.from_pretrained(gname).eval()
    fem = {v.lower(): k for k, v in gm.config.id2label.items()}["female"]
    mos = torch.hub.load("tarepan/SpeechMOS:v1.2.0", "utmos22_strong", trust_repo=True).eval()

    def emb(x):
        with torch.no_grad(): e = enc.encode_batch(torch.from_numpy(x)[None]).squeeze().numpy()
        return e / np.linalg.norm(e)
    # cast embeddings (cached by file mtime)
    names = open("work/anchor_ecapa.txt").read().split("\n") if os.path.exists("work/anchor_ecapa.txt") else []
    E = np.load("work/anchor_ecapa.npy") if names else np.zeros((0, 192))
    feats = json.load(open("work/cast_features.json", encoding="utf-8"))
    bins = {k: tercile([f[k] for f in feats.values()]) for k in ("jitter", "centroid", "rate")}
    prompt = {}
    for l in open("refs/cast/prompt_text", encoding="utf-8"):
        if "|" in l: k, v = l.rstrip("\n").split("|", 1); prompt[k] = v
    summary = []
    for spk in spks:
        g = GENDER.get(spk)
        if g not in ("man", "woman") or spk not in feats or spk not in prompt:
            print(f"{spk}: skipped (gender={g}, features={spk in feats}, anchor line={spk in prompt})"); continue
        accent, desc = describe(spk, feats[spk], bins)
        desc = desc.replace("high for a man, tenor-like", "medium-pitched, a lighter but clearly male voice")   # 'tenor-like' came out female (Liam, Hereford ...)
        if g == "woman": desc = desc.replace("Voice: a woman,", "Voice: a woman, clearly female,")
        desc = desc.replace("Grounded and natural, not theatrical.", "Expressive, lively intonation that rises and falls naturally; grounded, a real person talking, not a narrator.")   # Jorn round 2026-10-02: this design 3.0 vs 2.0
        od = os.path.join("out", "recast_auto", spk); os.makedirs(od, exist_ok=True)
        others = np.array([E[i] for i, n in enumerate(names) if n != spk]) if len(names) else np.zeros((0, 192))
        cands = []
        for sd in seeds:
            p = os.path.join(od, f"seed{sd}.wav")
            if not os.path.exists(p): open(p, "wb").write(design(prompt[spk], desc, sd))
            x, _ = load(p)
            with torch.no_grad():
                pf = float(gm(**gfe(x, sampling_rate=16000, return_tensors="pt")).logits.softmax(-1)[0][fem])
                m = float(mos(torch.from_numpy(x)[None], 16000).item())
            e = emb(x); sims = others @ e if len(others) else np.zeros(1)
            k = int(np.argmax(sims)); near = [n for n in names if n != spk][k] if len(others) else ""
            ok = pf > 0.9 if g == "woman" else pf < 0.1
            mv = signal_stats(x)["f0_st_sd"]                # pitch movement of the anchor; rendered lines inherit it (r = 0.86)
            score = (0 if ok else -10) - 3 * max(0.0, float(sims.max()) - 0.5) + 0.4 * min(mv, 5.5) + 0.3 * (m - 4)
            cands.append(dict(seed=sd, file=p, p_female=round(pf, 3), mos=round(m, 2), movement=round(mv, 2), max_sim=round(float(sims.max()), 3), nearest=near, gender_ok=ok, score=round(score, 3)))
            print(f"  {spk} seed {sd}: p_female={pf:.3f} movement={mv:.2f}st mos={m:.2f} max_sim={sims.max():.2f} ({near}) {'OK' if ok else 'WRONG GENDER'}", flush=True)
        best = max(cands, key=lambda c: c["score"])
        json.dump(dict(speaker=spk, gender=g, description=desc, candidates=cands, pick=best), open(os.path.join(od, "choice.json"), "w", encoding="utf-8"), indent=1)
        summary.append((spk, g, best)); print(f"{spk}: pick seed {best['seed']} (gender_ok={best['gender_ok']}, movement={best['movement']}, mos={best['mos']}, max_sim={best['max_sim']} to {best['nearest']})", flush=True)
        if a.apply and best["gender_ok"]:
            stamp = time.strftime("%m%d-%H%M"); dst = f"refs/cast/{spk}.wav"
            if os.path.exists(dst): shutil.move(dst, f"{dst}.bak-{stamp}")
            shutil.copy(best["file"], dst)
            rows = open("work/cast.tsv", encoding="utf-8").read().splitlines()
            for i, l in enumerate(rows):
                r = l.split("\t")
                if r[0].upper() == spk and len(r) >= 9: r[7] = accent; r[8] = desc + f" [auto-recast seed{best['seed']}]"; rows[i] = "\t".join(r)
            open("work/cast.tsv", "w", encoding="utf-8").write("\n".join(rows) + "\n")
            ov = "work/cast_overrides.tsv"
            open(ov, "a", encoding="utf-8").write(f"{spk}\t{best['file']}\t{desc}\t{stamp}\n")
            if spk in names: E[names.index(spk)] = emb(load(dst)[0])                        # later picks see the new voice
            else: names.append(spk); E = np.vstack([E, emb(load(dst)[0])])
            np.save("work/anchor_ecapa.npy", E); open("work/anchor_ecapa.txt", "w").write("\n".join(names))
            print(f"  applied -> {dst}", flush=True)
        elif a.apply: print(f"  NOT applied: no candidate passed the gender check", flush=True)
    print("\nspeaker\tgender\tseed\tp_female\tmos\tmax_sim\tnearest")
    for spk, g, b in summary: print(f"{spk}\t{g}\t{b['seed']}\t{b['p_female']}\t{b['mos']}\t{b['max_sim']}\t{b['nearest']}")


if __name__ == "__main__":
    main()
