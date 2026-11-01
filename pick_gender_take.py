r"""Re-take lines until the take is heard as the speaker's gender: tries seeds, keeps the take with the best gender score.
Input: a line set of one gender, e.g. the mismatches gender_lines.py writes. Needs the audio server; re-install afterwards.
usage: .venv-audit\Scripts\python pick_gender_take.py <lines.tsv> man|woman [first seed offset, default 10]"""
import sys, os, glob, json, hashlib, shutil, torch
P = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, P); os.chdir(P); torch.set_num_threads(4)
from audit_audio import load, tsv
from anchor_bench import speech
from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
n = "alefiury/wav2vec2-large-xlsr-53-gender-recognition-librispeech"
fe = AutoFeatureExtractor.from_pretrained(n); m = AutoModelForAudioClassification.from_pretrained(n).eval()
fem = {v.lower(): k for k, v in m.config.id2label.items()}["female"]
lines, want = sys.argv[1], sys.argv[2]                      # line set tsv, "man"|"woman"
dirs = {}
for f in glob.glob("work/batches/*.dir.tsv"):
    for r in tsv(f): dirs[r["wav"].upper()] = r["instruction"]
prompt = dict(l.rstrip("\n").split("|", 1) for l in open("refs/cast/prompt_text", encoding="utf-8") if "|" in l)
def score(p):
    x, _ = load(p)
    with torch.no_grad(): pf = float(m(**fe(x, sampling_rate=16000, return_tensors="pt")).logits.softmax(-1)[0][fem])
    return pf if want == "woman" else 1 - pf
os.makedirs("out/takes", exist_ok=True)
for r in tsv(lines):
    w = r["wav"].upper(); spk = r["speaker"]; best = ("out/final/" + w[:-4] + ".wav", score("out/final/" + w[:-4] + ".wav"))
    base = int(hashlib.md5(w.encode()).hexdigest()[:8], 16) % 2_000_000_000
    for k in range(int(sys.argv[3]) if len(sys.argv) > 3 else 10, (int(sys.argv[3]) if len(sys.argv) > 3 else 10) + 8):
        if best[1] > 0.9: break
        p = f"out/takes/{w[:-4]}_s{k}.wav"
        open(p, "wb").write(speech({"model": "breeze", "input": r["text"], "voice_ref": os.path.abspath(f"refs/cast/{spk}.wav"), "reference_text": prompt[spk],
                                    "seed": base + k, "options": {"instruction": dirs.get(w, ""), "guidance_scale": 3.5}}))
        s = score(p)
        if s > best[1]: best = (p, s)
    if best[0] != "out/final/" + w[:-4] + ".wav": shutil.copy(best[0], "out/final/" + w[:-4] + ".wav")
    print(f"{w:55s} best {want} score {best[1]:.2f} from {os.path.basename(best[0])}", flush=True)
