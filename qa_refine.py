"""Re-derive QA flags from work/qa_all.tsv with saner rules: numbers spelled out before WER, WER only on lines of
4+ words at >= 0.6, length ratio only outside 0.25-2.5x. Writes work/qa_flags.tsv."""
import os, re, sys
P = os.path.dirname(os.path.abspath(__file__))
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()
def num2words(n):
    if n < 20: return ONES[n]
    if n < 100: return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    if n < 1000: return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + num2words(n % 100))
    return str(n)
def norm(s):
    s = s.lower().replace("’", "'").replace("-", " ")
    s = re.sub(r"[0-9]+", lambda m: num2words(int(m.group())) if len(m.group()) <= 4 else m.group(), s)
    s = s.replace("all right", "alright").replace("okay", "ok")
    return re.sub(r"[^a-z' ]+", " ", s).split()
def wer(ref, hyp):
    r, h = norm(ref), norm(hyp)
    if not r: return 0.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]; d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1])); prev = cur
    return d[len(h)] / len(r)
text = {}
for l in open(os.path.join(P, "work", "ou_lines.tsv"), encoding="utf-8"):      # every game line (block, wav, text), so stock lines get a WER check too
    r = l.rstrip("\n").split("\t")
    if len(r) >= 3 and r[1].upper().endswith(".WAV"): text[r[1].upper()] = r[2]
for l in open(os.path.join(P, "work", "stage1_lines.tsv"), encoding="utf-8"):
    r = l.rstrip("\n").split("\t")
    if len(r) >= 3: text[r[1].upper()] = r[2]
rows = [l.rstrip("\n").split("\t") for l in open(os.path.join(P, "work", "qa_all.tsv"), encoding="utf-8")]
hdr = rows[0]; rows = [dict(zip(hdr, r)) for r in rows[1:] if len(r) == len(hdr)]
flags = []
for r in rows:
    src = text.get(r["wav"], ""); w = wer(src, r["transcript"]); ratio = float(r["ratio"]); secs = float(r["secs"])
    reason = []
    if len(norm(src)) >= 4 and w >= 0.6: reason.append(f"wer{w:.2f}")
    if len(norm(src)) == 3 and w >= 1.0 and secs > 0.3: reason.append(f"wer{w:.2f}")   # 1-2 word exclamations: ASR is unreliable, length ratio guards them instead
    if ratio and (ratio < 0.25 or ratio > 2.5): reason.append(f"len{ratio:.2f}")
    if secs > 30 or secs < 0.2: reason.append("dur")
    if reason: flags.append((r["wav"], r["speaker"], ",".join(reason)))
with open(os.path.join(P, "work", "qa_flags.tsv"), "w", encoding="utf-8") as f:
    f.write("wav\tspeaker\treason\n")
    for w, s, rs in flags: f.write(f"{w}\t{s}\t{rs}\n")
print(f"refined flags: {len(flags)} of {len(rows)} ({100*len(flags)/len(rows):.1f}%)")
