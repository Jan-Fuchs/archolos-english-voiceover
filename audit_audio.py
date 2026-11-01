"""Per-line audio audit of rendered lines: speaker similarity to the anchor (ECAPA), predicted naturalness (UTMOS22),
pitch and pitch movement, pace, silences, clipping and cut-off endings. Runs on CPU in its own venv (.venv-audit:
torch CPU, torchaudio, speechbrain, soundfile). Resumable; appends to work/audit_audio.tsv.

usage: .venv-audit\\Scripts\\python audit_audio.py [--set dia|svm|all] [--threads 6] [--ref pl|en --sample N]
  --ref pl / en scores N random originals from the Polish / StoneEyedJax archives instead (baseline for UTMOS).
"""
import argparse, glob, os, random, struct, subprocess, sys, time
import numpy as np, soundfile as sf, torch, torchaudio
P = os.path.dirname(os.path.abspath(__file__)); W = os.path.join(P, "work")
D = os.path.join(os.environ.get("ARCHOLOS_DIR", "C:/Program Files (x86)/Steam/steamapps/common/TheChroniclesOfMyrtana"), "Data")
FF = os.environ.get("FFMPEG", "ffmpeg")
SR = 16000
COLS = ["wav", "speaker", "secs", "sim", "mos", "f0", "f0_st_sd", "cps", "lead", "trail", "max_gap", "clip", "rms_db", "end_db"]


def tsv(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8")]
    return [dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])]


def catalog(pattern):
    cat = {}
    for p in sorted(glob.glob(os.path.join(D, pattern))):
        if os.path.getsize(p) == 0: continue
        f = open(p, "rb"); f.seek(272); ne = struct.unpack("<I", f.read(4))[0]; f.seek(296)
        for _ in range(ne):
            e = f.read(80); typ = struct.unpack_from("<I", e, 72)[0]
            if not typ & 0x80000000:
                cat[e[:64].decode("latin-1").rstrip(" \x00").upper()] = (p,) + struct.unpack_from("<II", e, 64)
    return cat


def decode_entry(ent):
    p, off, sz = ent; f = open(p, "rb"); f.seek(off); raw = f.read(sz)
    r = subprocess.run([FF, "-v", "error", "-f", "wav", "-i", "pipe:0", "-ac", "1", "-ar", str(SR), "-f", "s16le", "pipe:1"], input=raw, capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def load(path):
    x, sr = sf.read(path, dtype="float32", always_2d=True); x = x.mean(1)
    clip = float(np.mean(np.abs(x) > 0.995))
    if sr != SR: x = torchaudio.functional.resample(torch.from_numpy(x), sr, SR).numpy()
    return x, clip


def signal_stats(x):
    hop, frame = 160, 640                                         # 10 ms hop, 40 ms frames
    n = max(1, (len(x) - frame) // hop)
    fr = np.lib.stride_tricks.sliding_window_view(x, frame)[::hop][:n]
    rms = np.sqrt((fr ** 2).mean(1) + 1e-12); db = 20 * np.log10(rms + 1e-9)
    peak = db.max(); voiced = db > peak - 35                      # speech = within 35 dB of the loudest frame
    idx = np.flatnonzero(voiced)
    if len(idx) == 0: return dict(lead=0, trail=0, max_gap=0, rms_db=-99, end_db=-99, f0=0, f0_st_sd=0)
    lead, trail = idx[0] * hop / SR, (n - 1 - idx[-1]) * hop / SR
    gaps = np.diff(idx); max_gap = float((gaps.max() - 1) * hop / SR) if len(gaps) else 0.0
    end_db = float(db[max(0, n - 3):].max() - peak)               # level of the very last 30 ms vs the peak: high = cut off mid-word
    # pitch: normalised autocorrelation on loud frames, 60-400 Hz
    lo, hi = SR // 400, SR // 60
    loud = fr[db > peak - 20]
    f0 = []
    if len(loud):
        z = loud - loud.mean(1, keepdims=True)
        spec = np.fft.rfft(z, 2 * frame); ac = np.fft.irfft(np.abs(spec) ** 2)[:, :frame]
        ac = ac / (ac[:, :1] + 1e-9); seg = ac[:, lo:hi]; k = seg.argmax(1) + lo; ok = seg.max(1) > 0.5
        k2 = np.minimum(2 * k, frame - 1); dbl = (2 * k < hi) & (ac[np.arange(len(k)), k2] > 0.85 * ac[np.arange(len(k)), k])
        k = np.where(dbl, k2, k); f0 = SR / k[ok]
    f0 = np.asarray(f0)
    med = float(np.median(f0)) if len(f0) > 5 else 0.0
    sd = float(np.std(12 * np.log2(f0 / med))) if len(f0) > 5 else 0.0   # pitch movement in semitones (monotone -> low)
    return dict(lead=lead, trail=trail, max_gap=max_gap, rms_db=float(20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9)), end_db=end_db, f0=med, f0_st_sd=sd)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--set", default="dia"); ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--ref", default=""); ap.add_argument("--sample", type=int, default=400); ap.add_argument("--out", default=""); ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(); torch.set_num_threads(a.threads)
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy
    enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", savedir=os.path.join(P, "models", "audit", "ecapa"),
                                         run_opts={"device": "cpu"}, local_strategy=LocalStrategy.COPY)
    mos = torch.hub.load("tarepan/SpeechMOS:v1.2.0", "utmos22_strong", trust_repo=True); mos.eval()
    text = {r["wav"].upper(): r["text"] for r in tsv(os.path.join(W, "ou_lines.tsv")) if "wav" in r}
    jobs = []                                                     # (wav, speaker, loader)
    if a.ref:
        cat = catalog("KM_Speech*PL.mod" if a.ref == "pl" else "KM_Speech*EN.mod")
        names = sorted(n for n in cat if n.startswith(("DIA_", "TRIA_")) and n in text)
        random.Random(1).shuffle(names)
        jobs = [(n, a.ref.upper(), (lambda e: (lambda: (decode_entry(e), 0.0)))(cat[n])) for n in names[: a.sample]]
        outp = a.out or os.path.join(W, f"audit_ref_{a.ref}.tsv")
    else:
        last = {}
        for r in tsv(os.path.join(W, "render_log.tsv")): last[r["wav"].upper()] = r
        inst = [os.path.basename(l.strip()).upper() for l in open(os.path.join(W, "installed.txt"), encoding="utf-8") if l.strip()]
        sv = {r["voice"]: r["anchor"] for r in tsv(os.path.join(W, "svm_voices.tsv"))}
        for w in inst:
            is_svm = w.startswith("SVM_")
            if (a.set == "dia" and is_svm) or (a.set == "svm" and not is_svm): continue
            spk = sv.get(w.split("_")[1], "?") if is_svm else last.get(w, {}).get("speaker", "?")
            path = os.path.join(P, "out", "final", w[:-4] + ".wav")
            jobs.append((w, spk, (lambda p: (lambda: load(p)))(path)))
        outp = a.out or os.path.join(W, "audit_audio.tsv")
    done = set()
    if os.path.exists(outp): done = {l.split("\t")[0] for l in open(outp, encoding="utf-8")}
    else: open(outp, "w", encoding="utf-8").write("\t".join(COLS) + "\n")
    out = open(outp, "a", encoding="utf-8")
    anchors = {}
    def anchor_emb(spk):
        if spk not in anchors:
            p = os.path.join(P, "refs", "cast", spk + ".wav")
            anchors[spk] = enc.encode_batch(torch.from_numpy(load(p)[0])[None]).squeeze() if os.path.exists(p) else None
        return anchors[spk]
    todo = [j for j in jobs if j[0] not in done]; t0 = time.time()
    if a.limit: todo = todo[: a.limit]
    print(f"{len(todo)} to audit ({len(done) - 1 if done else 0} done) -> {outp}", flush=True)
    for i, (w, spk, loader) in enumerate(todo, 1):
        try:
            x, clip = loader()
            if len(x) < SR // 4: raise ValueError("too short")
            xt = torch.from_numpy(x)[None]
            with torch.no_grad():
                m = float(mos(xt, SR).item())
                e = enc.encode_batch(xt).squeeze(); ae = None if a.ref else anchor_emb(spk)
                sim = float(torch.nn.functional.cosine_similarity(e, ae, dim=0)) if ae is not None else float("nan")
            s = signal_stats(x); secs = len(x) / SR
            cps = len(text.get(w, "")) / max(0.3, secs - s["lead"] - s["trail"])
            row = [w, spk, f"{secs:.2f}", f"{sim:.3f}", f"{m:.3f}", f"{s['f0']:.0f}", f"{s['f0_st_sd']:.2f}", f"{cps:.1f}",
                   f"{s['lead']:.2f}", f"{s['trail']:.2f}", f"{s['max_gap']:.2f}", f"{clip:.4f}", f"{s['rms_db']:.1f}", f"{s['end_db']:.1f}"]
        except Exception as ex:
            row = [w, spk] + ["err"] * (len(COLS) - 2); print(w, ex, flush=True)
        out.write("\t".join(row) + "\n")
        if i % 200 == 0:
            out.flush(); el = time.time() - t0
            print(f"{i}/{len(todo)}  {el / i:.2f} s/line  eta {(len(todo) - i) * el / i / 60:.0f} min", flush=True)
    out.close(); print("done", flush=True)


if __name__ == "__main__":
    main()
