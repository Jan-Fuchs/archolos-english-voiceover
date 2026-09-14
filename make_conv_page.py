"""Build the conversation-compare page: whole conversations, several versions each, labels shuffled per conversation.
Audio is embedded as base64 MP3 so the page is one file.
usage: python make_conv_page.py --lines work/demo/ship_lines.tsv --versions current=out/final v2=out/demo_ship_v2 v2pick=out/demo_ship_v2_pick
                                --round r9 --out out/conv_page.html [--extra "Sigh test=out/demo_sigh"] [--intro "..."]
"""
import argparse, base64, glob, json, os, random, re, subprocess, sys
P = os.path.dirname(os.path.abspath(__file__))
FF = os.environ.get("FFMPEG", "ffmpeg")                       # ffmpeg on PATH, or FFMPEG=<full path>
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def tsv(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8")]
    return [dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])]


def mp3_b64(wav):
    r = subprocess.run([FF, "-v", "error", "-i", wav, "-ac", "1", "-c:a", "libmp3lame", "-b:a", "48k", "-f", "mp3", "pipe:1"], capture_output=True, check=True)
    return "data:audio/mpeg;base64," + base64.b64encode(r.stdout).decode()


def esc(s): return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", required=True); ap.add_argument("--versions", nargs="+", required=True, help="key=folder ...")
    ap.add_argument("--round", default="c1"); ap.add_argument("--out", default=os.path.join(P, "out", "conv_page.html"))
    ap.add_argument("--extra", action="append", default=[], help='"Title=folder" of labelled (non-blind) clips')
    ap.add_argument("--intro", default="")
    ap.add_argument("--labels", nargs="*", default=None, help="fixed version labels in the given order (no shuffle, not blind)")
    ap.add_argument("--conv", default="", help="only this conversation title")
    ap.add_argument("--title", default="Ship Conversations")
    args = ap.parse_args()
    versions = [v.split("=", 1) for v in args.versions]
    convs = {}
    for l in tsv(args.lines):
        if not args.conv or l.get("conv", l["block"]) == args.conv: convs.setdefault(l.get("conv", l["block"]), []).append(l)
    rng = random.Random(args.round); data = {"round": args.round, "intro": args.intro, "convs": [], "extras": []}
    labels = "XYZWV"
    for ci, (title, ls) in enumerate(convs.items()):
        order = list(range(len(versions)))
        if not args.labels: rng.shuffle(order)
        vs = []
        for li, vi in enumerate(order):
            key, folder = versions[vi]; clips = []
            for l in ls:
                p = os.path.join(folder, l["wav"].upper()[:-4] + ".wav")
                clips.append(mp3_b64(p) if os.path.exists(p) else "")
            vs.append({"label": esc(args.labels[li]) if args.labels else labels[li], "key": key, "clips": clips})
            missing = sum(1 for c in clips if not c)
            if missing: print(f"  {title}: version {key} missing {missing} clips")
        blocks = []
        for l in ls:
            if l["block"] not in blocks: blocks.append(l["block"])
        def heading(l):
            if l["block"] != ls[0]["block"] and (ls.index(l) == 0 or ls[ls.index(l) - 1]["block"] != l["block"]):
                k = blocks.index(l["block"])
                return f"Branch {k} of {len(blocks) - 1}: {l['block']} — an alternative path after the opening, not a continuation of the branch above"
            if ls.index(l) == 0 and len(blocks) > 1: return f"Opening: {l['block']}"
            return ""
        data["convs"].append({"id": f"c{ci}", "title": esc(title), "lines": [{"spk": esc(l["speaker"]), "text": esc(l["text"]), "wav": l["wav"], "head": esc(heading(l))} for l in ls], "versions": vs})
    for e in args.extra:
        title, folder = e.split("=", 1)
        clips = [{"label": os.path.basename(w)[:-4], "src": mp3_b64(w)} for w in sorted(glob.glob(os.path.join(folder, "*.wav")))]
        data["extras"].append({"title": esc(title), "note": "Labelled, not blind.", "clips": clips})
    tpl = open(os.path.join(P, "conv_page_template.html"), encoding="utf-8").read()
    html = tpl.replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    html = html.replace("<title>Ship Conversations</title>", "<title>" + esc(args.title) + "</title>", 1).replace("<h1>Ship conversations</h1>", "<h1>" + esc(args.title) + "</h1>", 1)
    open(args.out, "w", encoding="utf-8").write(html)
    print(f"wrote {args.out}: {len(data['convs'])} conversations, {len(versions)} versions, {os.path.getsize(args.out)/1e6:.1f} MB")


if __name__ == "__main__":
    main()
