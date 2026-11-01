r"""Stage voices for one-off NPCs whose lines the script never ties to a named character: gender from the Polish actor's
audio (wav2vec2 gender classifier), voice features from the same audio (design_anchors.features), anchor line = their
longest line. Input: work/rest_unvoiced.tsv (build_rest.py). Output: work/extra_cast.json (merged into the cast by
run_extras.py) and work/extra_npc_lines.tsv.
usage: .venv-audit\Scripts\python stage_extra_cast.py"""
import sys, os, re, json, collections, numpy as np, torch
P = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, P); os.chdir(P); torch.set_num_threads(2)
from audit_audio import catalog, decode_entry, tsv
from design_anchors import features
from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
n = "alefiury/wav2vec2-large-xlsr-53-gender-recognition-librispeech"
fe = AutoFeatureExtractor.from_pretrained(n); gm = AutoModelForAudioClassification.from_pretrained(n).eval()
fem = {v.lower(): k for k, v in gm.config.id2label.items()}["female"]
def family(w, s):
    if s.startswith("?"): return re.sub(r"^\?[A-Z]+_\d+_", "", s)
    if s: return s
    k = re.sub(r"_\d+_\d+(_[A-Z])?\.WAV$", "", w); k = re.sub(r"^(INFO|IA|DIA|NONE)_", "", k)
    return k.split("_")[0]
rows = [r for r in tsv("work/rest_unvoiced.tsv")]
fam = collections.defaultdict(list)
for r in rows: fam[family(r["wav"].upper(), r["script_speaker"])].append(r)
pl = catalog("KM_Speech*PL.mod"); out = {}
for f, rs in fam.items():
    ws = [r["wav"].upper() for r in rs if r["wav"].upper() in pl]
    x = np.concatenate([decode_entry(pl[w]) for w in ws[:12]]) if ws else np.zeros(16000, dtype=np.float32)
    with torch.no_grad(): pf = float(gm(**fe(x[:16000 * 15], sampling_rate=16000, return_tensors="pt")).logits.softmax(-1)[0][fem])
    ft = features(x[:16000 * 15]); ft["lines"] = len(rs); ft["sec"] = round(len(x) / 16000, 1)
    texts = [r["text"] for r in rs]
    own = [t for t in texts if 12 <= len(t.split()) <= 30] or texts
    out[f] = dict(gender="woman" if pf > 0.5 else "man", p_female=round(pf, 3), features=ft, anchor_line=max(own, key=len), lines=[r["wav"] for r in rs])
    print(f"{f:14s} {len(rs):4d} lines  {out[f]['gender']:5s} (p_female {pf:.2f}, {len(ws)} Polish lines)  f0 {ft['f0']:.0f}", flush=True)
json.dump(out, open("work/extra_cast.json", "w", encoding="utf-8"), indent=1)
with open("work/extra_npc_lines.tsv", "w", encoding="utf-8") as f:
    f.write("speaker\twav\ttext\tblock\ttier\n")
    for k, v in out.items():
        for r in fam[k]: f.write(f"{k}\t{r['wav'].upper()}\t{r['text']}\t\tfiller\n")
print("staged", len(out), "voices ->", "work/extra_cast.json, work/extra_npc_lines.tsv")
