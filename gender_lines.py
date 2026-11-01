r"""Per-line gender check of everything installed: classify each rendered line with a wav2vec2 gender classifier and
compare with the speaker's gender (script/LLM table; stock lines: the voice set's anchor). Emotional takes (screams,
pleading) can drift into the other gender even when the anchor is right. Resumable; writes work/gender_lines.tsv and
work/gender_drift_lines.tsv (line set of the mismatches, for pick_gender_take.py).
usage: .venv-audit\Scripts\python gender_lines.py [--threads 6]
"""
import os, sys, torch
P = os.path.dirname(os.path.abspath(__file__)); os.chdir(P); sys.path.insert(0, P)
from audit_audio import load, tsv
from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
torch.set_num_threads(int(sys.argv[sys.argv.index("--threads") + 1]) if "--threads" in sys.argv else 6)
n = "alefiury/wav2vec2-large-xlsr-53-gender-recognition-librispeech"
fe = AutoFeatureExtractor.from_pretrained(n); m = AutoModelForAudioClassification.from_pretrained(n).eval()
fem = {v.lower(): k for k, v in m.config.id2label.items()}["female"]
g = {r["speaker"]: r["gender"] for r in tsv("work/gender_llm.tsv")}
g.update({r["speaker"]: r["gender"] for r in tsv("work/gender_script.tsv")}); g["MARVIN"] = "man"
last = {}
for r in tsv("work/render_log.tsv"): last[r["wav"].upper()] = r["speaker"]
text = {r["wav"].upper(): r["text"] for r in tsv("work/ou_lines.tsv")}
inst = [os.path.basename(l.strip()).upper() for l in open("work/installed.txt", encoding="utf-8") if l.strip()]
out = "work/gender_lines.tsv"; done = set()
if os.path.exists(out): done = {l.split("\t")[0] for l in open(out, encoding="utf-8")}
else: open(out, "w", encoding="utf-8").write("wav\tspeaker\twant\tp_female\n")
f = open(out, "a", encoding="utf-8"); k = 0
for w in inst:
    if w in done or w not in last: continue
    spk = last[w]; want = g.get(spk)
    if want not in ("man", "woman"): continue
    p = f"out/final/{w[:-4]}.wav"
    if not os.path.exists(p): continue
    x, _ = load(p)
    if len(x) < 8000: continue                                   # under 0.5 s: too short to judge
    with torch.no_grad(): pf = float(m(**fe(x, sampling_rate=16000, return_tensors="pt")).logits.softmax(-1)[0][fem])
    f.write(f"{w}\t{spk}\t{want}\t{pf:.3f}\n"); k += 1
    if k % 500 == 0: f.flush(); print(k, flush=True)
f.close()
rows = tsv(out); bad = [r for r in rows if (r["want"] == "man" and float(r["p_female"]) > 0.5) or (r["want"] == "woman" and float(r["p_female"]) < 0.5)]
with open("work/gender_drift_lines.tsv", "w", encoding="utf-8") as o:
    o.write("speaker\twav\ttext\tblock\ttier\n")
    for r in bad: o.write(f"{r['speaker']}\t{r['wav']}\t{text.get(r['wav'], '')}\t\tquest\n")
print(f"checked {len(rows)} lines, {len(bad)} heard as the wrong gender -> work/gender_drift_lines.tsv")
