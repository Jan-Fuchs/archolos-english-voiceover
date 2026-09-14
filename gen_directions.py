"""Write one delivery direction per dialogue line with a chat model, from the dialogue context alone (no listening).

For every target line the model gets the speaker, the wav file name (quest/beat tokens are informative), and +-2 lines of
the same conversation; it returns 6-18 words on HOW the line is said. Output: a TSV (wav<TAB>instruction) that
render_all.py passes to the TTS as the instruction. Any capable model works; in blind rounds the writer model made no
measurable difference (Opus 5 = Sonnet 5 = hand-written), the TTS take-to-take variance did.

Backends (picked automatically from the environment, or forced with --provider):
  anthropic  ANTHROPIC_API_KEY (or an `ant auth login` profile)      pip install anthropic     default model claude-opus-5
  openai     OPENAI_API_KEY and/or OPENAI_BASE_URL - OpenAI, OpenRouter, Ollama (http://localhost:11434/v1), LM Studio,
             llama.cpp server, anything speaking /v1/chat/completions   no extra package         --model is required
  none       --dump writes the prompt + all lines to a text file; paste it into any assistant and save its output as the TSV

usage:
  python gen_directions.py --lines work/my_lines.tsv --out work/batches/my.dir.tsv [--model X] [--batch 25] [--effort medium]
  python gen_directions.py --lines work/my_lines.tsv --dump work/my.ctx.txt
  python gen_directions.py --all --out work/directions_all.tsv [--limit N]
Speakers come from the line set's `speaker` column, else work/speaker_script.tsv (who_speaks.py), else the file name.
Resumable: an existing --out file is continued.
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.error

P = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SYSTEM = """You write delivery directions for a voice actor performing lines from The Chronicles of Myrtana: Archolos, a Gothic II total conversion. The register is Gothic: grounded, unhurried, dry, understated; grave men in a hard medieval world. Never chirpy, never theatrical.

For each line you get: the speaker, the dialogue file name (quest and beat tokens are informative, e.g. SECONDWARN, BADFIGHTER, TRAP, FINISH, HELLO), the line itself, and the surrounding lines of the same conversation in order. MARVIN is the player character, a young man with no illusions.

Write ONE direction per line: 6-18 words describing HOW it is said, not what it means. Cover tone, energy, pace, and any single emphasis or pause worth naming. Prefer restraint; most lines are quiet. Do not invent context that is not in the conversation. Never ask for sighs, breaths, laughs or other non-speech sounds; the synthesizer cannot produce them.

Pace rule: the default for every line is unhurried - say so explicitly ("slow", "unhurried", "takes his time"). Only call for normal or brisk pace when the character is plainly impatient, urgent, angry, or mid-action; then the faster pace itself carries that meaning.

Return only a JSON array of objects: {"wav": "<exact file name>", "instruction": "<direction>"}. No prose, no code fences."""

SPEAKER = {}          # wav (upper) -> speaker token, filled from the line set / speaker_script.tsv


def tsv(path):
    rows = [l.rstrip("\n").split("\t") for l in open(path, encoding="utf-8")]
    return [dict(zip(rows[0], r)) for r in rows[1:] if len(r) == len(rows[0])]


def load_table():
    """All OU lines in file order, plus an index from wav -> position and block."""
    lines = tsv(os.path.join(P, "work", "ou_lines.tsv"))
    lines = [l for l in lines if l["wav"].upper().endswith(".WAV")]
    idx = {l["wav"].upper(): i for i, l in enumerate(lines)}
    return lines, idx


def load_speakers(lines_tsv):
    """Speaker per wav: the line set's own column first, then who_speaks.py's script resolution."""
    p = os.path.join(P, "work", "speaker_script.tsv")
    if os.path.exists(p):
        for r in tsv(p):
            if not r["speaker"].startswith("?"): SPEAKER[r["wav"].upper()] = r["speaker"].upper()
    if lines_tsv:
        for r in tsv(lines_tsv):
            if r.get("speaker"): SPEAKER[r["wav"].upper()] = r["speaker"].upper()


def speaker_of(wav):
    if wav.upper() in SPEAKER: return SPEAKER[wav.upper()]
    if re.search(r"_15_\d+\.WAV$", wav, re.I): return "MARVIN"          # file-name fallback: owner token, 15 = hero
    m = re.match(r"(?:DIA|TRIA)_([^_]+)_", wav, re.I)
    return m.group(1).upper() if m else "NPC"


def context_for(lines, idx, wav, before=2, after=2):
    i = idx[wav.upper()]
    block = lines[i]["block"]
    out = []
    for j in range(max(0, i - before), min(len(lines), i + after + 1)):
        if lines[j]["block"] != block:
            continue
        out.append(("> " if j == i else "  ") + f"{speaker_of(lines[j]['wav'])}: {lines[j]['text']}")
    return "\n".join(out)


def build_user_prompt(batch, lines, idx):
    parts = []
    for l in batch:
        wav = l["wav"]
        parts.append(f"### {wav}\nspeaker: {speaker_of(wav)}\nconversation (target line marked with >):\n{context_for(lines, idx, wav)}")
    return "\n\n".join(parts)


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("["), text.rfind("]")
    return json.loads(text[start:end + 1])


# ---------------------------------------------------------------- backends: each returns (text, tokens_in, tokens_out)
class Backend:
    def __init__(self, args):
        self.model, self.effort = args.model, args.effort

    def complete(self, prompt): raise NotImplementedError


class AnthropicBackend(Backend):
    def __init__(self, args):
        super().__init__(args)
        import anthropic                                   # official SDK; credentials from ANTHROPIC_API_KEY or an `ant auth login` profile
        self.sdk = anthropic; self.client = anthropic.Anthropic()
        self.model = self.model or "claude-opus-5"; self.effort = self.effort or "medium"

    def complete(self, prompt):
        a = self.sdk
        while True:
            try:
                resp = self.client.messages.create(
                    model=self.model, max_tokens=16000,
                    system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                    output_config={"effort": self.effort},
                    messages=[{"role": "user", "content": prompt}])
                break
            except a.RateLimitError as e:
                wait = int(e.response.headers.get("retry-after", "30")); print(f"rate limited, sleeping {wait}s"); time.sleep(wait)
            except a.APIStatusError as e:
                if e.status_code >= 500: print(f"server error {e.status_code}, retrying in 30s"); time.sleep(30); continue
                sys.exit(f"API error {e.status_code}: {e.message}")
            except a.APIConnectionError:
                print("connection error, retrying in 30s"); time.sleep(30)
        if resp.stop_reason == "refusal": sys.exit(f"refusal: {resp.stop_details}")
        if resp.stop_reason == "max_tokens": print("warning: output cut at max_tokens; lower --batch")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        u = resp.usage
        return text, u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0), u.output_tokens


class OpenAIBackend(Backend):
    """Any server speaking the OpenAI chat-completions protocol; plain HTTP, no package needed."""
    def __init__(self, args):
        super().__init__(args)
        self.base = (args.base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.key = os.environ.get("OPENAI_API_KEY", "")
        self.model = self.model or os.environ.get("OPENAI_MODEL")
        if not self.model: sys.exit("openai backend: pass --model (or set OPENAI_MODEL), e.g. --model gpt-5 or --model llama3.3")

    def complete(self, prompt):
        body = {"model": self.model, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
        if self.effort: body["reasoning_effort"] = self.effort          # only sent when asked for; many servers reject unknown fields
        hdr = {"Content-Type": "application/json"}
        if self.key: hdr["Authorization"] = f"Bearer {self.key}"
        req = urllib.request.Request(self.base + "/chat/completions", json.dumps(body).encode("utf-8"), hdr)
        while True:
            try:
                with urllib.request.urlopen(req, timeout=600) as r: data = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "replace")[:400]
                if e.code == 429 or e.code >= 500:
                    wait = int(e.headers.get("retry-after", "30") or 30); print(f"HTTP {e.code}, retrying in {wait}s"); time.sleep(wait); continue
                sys.exit(f"HTTP {e.code}: {msg}")
            except urllib.error.URLError as e:
                print(f"connection error ({e.reason}), retrying in 30s"); time.sleep(30)
        ch = data["choices"][0]
        if ch.get("finish_reason") == "length": print("warning: output cut by the server's length limit; lower --batch")
        u = data.get("usage") or {}
        return ch["message"].get("content") or "", u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def pick_backend(args):
    p = args.provider
    if p == "auto":
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or (args.model or "").startswith("claude"): p = "anthropic"
        elif os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_BASE_URL"): p = "openai"
        else:
            sys.exit("no model backend found. Set ANTHROPIC_API_KEY, or OPENAI_API_KEY / OPENAI_BASE_URL (+ --model), "
                     "or use --dump and run the prompt in any assistant by hand.")
    return AnthropicBackend(args) if p == "anthropic" else OpenAIBackend(args)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", help="TSV with a 'wav' column (and ideally a 'speaker' column)")
    ap.add_argument("--all", action="store_true", help="every dialogue line in the OU table")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="", help="directions TSV to write (continued if it exists)")
    ap.add_argument("--provider", default="auto", choices=["auto", "anthropic", "openai"])
    ap.add_argument("--model", default=None, help="anthropic default claude-opus-5; openai: required (or OPENAI_MODEL)")
    ap.add_argument("--base-url", default=None, help="OpenAI-compatible endpoint, default OPENAI_BASE_URL or https://api.openai.com/v1")
    ap.add_argument("--batch", type=int, default=25, help="lines per request")
    ap.add_argument("--effort", default=None, choices=["low", "medium", "high", "xhigh", "max"],
                    help="reasoning effort; anthropic default medium, openai: sent as reasoning_effort only when given")
    ap.add_argument("--dump", help="write system prompt + user prompt for all target lines to this file and exit (no model call)")
    args = ap.parse_args()
    if not args.dump and not args.out: ap.error("--out or --dump is required")

    lines, idx = load_table()
    load_speakers(args.lines)
    if args.all:
        targets = [l for l in lines if not l["wav"].upper().startswith("SVM_")]
    else:
        wanted = [r["wav"] for r in tsv(args.lines)]
        targets = [lines[idx[w.upper()]] for w in wanted if w.upper() in idx]
    if args.limit:
        targets = targets[: args.limit]

    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            f.write("SYSTEM PROMPT\n=============\n" + SYSTEM + "\n\nUSER PROMPT\n===========\n" + build_user_prompt(targets, lines, idx) + "\n")
        print(f"wrote {args.dump}: {len(targets)} lines"); return

    be = pick_backend(args)
    print(f"{len(targets)} lines, {type(be).__name__} model {be.model}, batch {args.batch}")
    done = {}
    if os.path.exists(args.out):  # resume
        for r in tsv(args.out):
            done[r["wav"]] = r["instruction"]
        print(f"resuming: {len(done)} already done")
    usage_in = usage_out = 0
    t0 = time.time()
    with open(args.out, "a" if done else "w", encoding="utf-8") as f:
        if not done:
            f.write("wav\tinstruction\n")
        todo = [l for l in targets if l["wav"] not in done]
        for b in range(0, len(todo), args.batch):
            batch = todo[b:b + args.batch]
            text, tin, tout = be.complete(build_user_prompt(batch, lines, idx))
            usage_in += tin; usage_out += tout
            try:
                items = parse_json(text)
            except Exception as e:
                print("could not parse batch response:", e); print(text[:400]); sys.exit(1)
            got = {it["wav"]: it["instruction"].strip() for it in items if "wav" in it and "instruction" in it}
            for l in batch:
                ins = got.get(l["wav"]) or got.get(l["wav"].upper()) or ""
                if ins:
                    f.write(f"{l['wav']}\t{ins}\n"); done[l["wav"]] = ins
            f.flush()
            print(f"  {min(b + args.batch, len(todo))}/{len(todo)}  tokens in={usage_in} out={usage_out}  {time.time() - t0:.0f}s")
    print(f"wrote {args.out}: {len(done)} directions")


if __name__ == "__main__":
    main()
