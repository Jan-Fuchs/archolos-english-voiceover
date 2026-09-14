"""QA pass over rendered lines: ASR round-trip (Qwen3-ASR via the server) against the source text, plus duration
sanity against the Polish original. Flags go to work/qa_flags.tsv (feed to render_all.py --redo with --seed-offset 1).
usage: python qa_all.py --lines work/stage1_lines.tsv [--wer 0.35] [--limit N]
"""
import argparse, glob, json, os, re, struct, sys, time, urllib.request
P = os.path.dirname(os.path.abspath(__file__)); BASE = "http://127.0.0.1:8080"
D = os.path.join(os.environ.get("ARCHOLOS_DIR", "C:/Program Files (x86)/Steam/steamapps/common/TheChroniclesOfMyrtana"), "Data")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def tsv(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8")]
    return [dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])]


def norm(s):
    s = s.lower().replace("’", "'"); s = re.sub(r"[^a-z0-9' ]+", " ", s); return s.split()


def wer(ref, hyp):
    r, h = norm(ref), norm(hyp)
    if not r: return 0.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]; d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1])); prev = cur
    return d[len(h)] / len(r)


def wav_seconds(path):
    b = open(path, "rb").read(64); i = b.find(b"fmt ")
    rate = struct.unpack_from("<I", b, i + 16)[0]; j = b.find(b"data")
    size = struct.unpack_from("<I", b, j + 4)[0] if j >= 0 else os.path.getsize(path) - 44
    return size / max(rate, 1)


def polish_seconds():
    out, rate = {}, {}
    for p in sorted(glob.glob(os.path.join(D, "KM_Speech*PL.mod"))):
        if os.path.getsize(p) == 0: continue
        f = open(p, "rb"); f.seek(272); ne = struct.unpack("<I", f.read(4))[0]; f.seek(296)
        ents = []
        for _ in range(ne):
            e = f.read(80); typ = struct.unpack_from("<I", e, 72)[0]
            if not typ & 0x80000000: ents.append((e[:64].decode("latin-1").rstrip(" \x00").upper(),) + struct.unpack_from("<II", e, 64))
        if ents:
            f.seek(ents[0][1]); w = f.read(64); k = w.find(b"fmt "); rate[p] = struct.unpack_from("<I", w, k + 16)[0] or 16000
            for n, off, sz in ents: out[n] = sz / rate[p]
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--lines", required=True); ap.add_argument("--wer", type=float, default=0.35); ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    lines = tsv(args.lines); pl = polish_seconds()
    qa_path = os.path.join(P, "work", "qa_all.tsv"); done = {}
    if os.path.exists(qa_path):
        for r in tsv(qa_path): done[r["wav"].upper()] = r
    else:
        open(qa_path, "w", encoding="utf-8").write("wav\tspeaker\twer\tsecs\tpl_secs\tratio\tflag\ttranscript\n")
    qa = open(qa_path, "a", encoding="utf-8"); n = flagged = 0; t0 = time.time()
    for l in lines:
        wav = l["wav"].upper(); out = os.path.join(P, "out", "final", wav[:-4] + ".wav")
        if wav in done or not os.path.exists(out): continue
        body = {"model": "qwen3-asr", "audio": out, "language": "en"}
        req = urllib.request.Request(BASE + "/v1/audio/transcriptions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r: hyp = json.load(r).get("text", "")
        except Exception as e:
            print("  asr error", wav, getattr(e, "code", ""), getattr(e, "reason", e)); continue
        w = wer(l["text"], hyp); secs = wav_seconds(out); pls = pl.get(wav, 0.0); ratio = secs / pls if pls else 0.0
        flag = []
        if w > args.wer: flag.append(f"wer{w:.2f}")
        if pls and (ratio < 0.45 or ratio > 2.2): flag.append(f"len{ratio:.2f}")
        if secs > 30: flag.append("long")
        qa.write(f"{wav}\t{l['speaker']}\t{w:.3f}\t{secs:.2f}\t{pls:.2f}\t{ratio:.2f}\t{','.join(flag)}\t{hyp.replace(chr(9),' ')}\n"); qa.flush()
        n += 1; flagged += bool(flag)
        if n % 200 == 0: print(f"  {n} checked, {flagged} flagged, {time.time()-t0:.0f}s")
        if args.limit and n >= args.limit: break
    qa.close()
    rows = tsv(qa_path); flags = [r for r in rows if r["flag"]]
    with open(os.path.join(P, "work", "qa_flags.tsv"), "w", encoding="utf-8") as f:
        f.write("wav\tspeaker\treason\n")
        for r in flags: f.write(f"{r['wav']}\t{r['speaker']}\t{r['flag']}\n")
    print(f"QA: {len(rows)} lines checked, {len(flags)} flagged ({100*len(flags)/max(len(rows),1):.1f}%) -> work/qa_flags.tsv")


if __name__ == "__main__":
    main()
