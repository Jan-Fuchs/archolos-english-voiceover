"""Who actually speaks each dialogue line, from the compiled script (GOTHIC.DAT) instead of the file name.
The DIA_/TRIA_ prefix is only the dialogue OWNER; in trialogues TRIA_Next(npc) makes `self` another NPC, and the
number in the file name is whatever the writer typed. This walks every C_INFO information function, its choice
functions (Info_AddChoice) and the functions it queues (AI_Function), tracking self/other, and records the first
argument of every AI_Output.
output: work/speaker_script.tsv  (wav, npc_instance, speaker_token, n_sites, conflict)
        + a comparison with the line sets given on the command line (default: stage1 + stage1b)
usage: python who_speaks.py [--lines work/stage1_lines.tsv ...]
"""
import os, re, sys, struct, bisect, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from npc_gender import load, walk, OPERAND4, OP_PUSHARRAY, T_INSTANCE, T_FUNC, T_STRING, T_PROTOTYPE, F_EXTERNAL
P = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OP_CALL, OP_CALLEXT, OP_PUSHINT, OP_PUSHVAR, OP_PUSHINST = 61, 62, 64, 65, 67


def main():
    args = sys.argv[1:]
    line_files = []
    while "--lines" in args:
        k = args.index("--lines"); line_files.append(args[k + 1]); del args[k:k + 2]
    if not line_files: line_files = [os.path.join(P, "work", "stage1_lines.tsv"), os.path.join(P, "work", "stage1b_lines.tsv")]
    syms, code = load(os.path.join(P, "work", "scripts", "KM_ScriptsEN_GOTHIC.DAT"))
    byname = {s["name"].upper(): s for s in syms if s["name"]}
    I = lambda n: byname[n]["i"]
    ai_output, info_addchoice = I("AI_OUTPUT"), I("INFO_ADDCHOICE")
    self_i, other_i, hero_i = I("SELF"), I("OTHER"), I("HERO")
    f_info, f_npc = I("C_INFO.INFORMATION"), I("C_INFO.NPC")
    tria_next = byname["TRIA_NEXT"]["val"]; ai_function = byname["AI_FUNCTION"]["val"]
    cls_info = I("C_INFO")

    def root_class(s):
        p = s["parent"]
        while p >= 0 and syms[p]["type"] == T_PROTOTYPE: p = syms[p]["parent"]
        return p
    # function address -> end address (next function start), for walking past early RETs
    funcs = sorted(s["val"] for s in syms if s["type"] == T_FUNC and s["val"] is not None and not s["flags"] & F_EXTERNAL)
    fend = {a: (funcs[k + 1] if k + 1 < len(funcs) else len(code)) for k, a in enumerate(funcs)}
    # C_INFO instances: npc + information function
    info_npc, info_fn = {}, {}
    for s in syms:
        if s["type"] != T_INSTANCE or root_class(s) != cls_info: continue
        last = None
        for pc, op, arg in walk(code, s["val"], syms):
            if op == OP_PUSHVAR and arg == f_npc and last is not None: info_npc[s["i"]] = last
            elif op == OP_PUSHVAR and arg == f_info and last is not None: info_fn[s["i"]] = last
            elif op in (OP_PUSHINT, OP_PUSHVAR, OP_PUSHINST): last = arg
    print(f"C_INFO instances: {len(info_npc)} with npc, {len(info_fn)} with information function")

    def npc_name(i):
        return syms[i]["name"].upper() if 0 <= i < len(syms) and syms[i]["name"] else f"#{i}"

    result = collections.defaultdict(collections.Counter)      # wav -> Counter(speaker instance)
    seen = set(); queue = []; reached = set()
    UNKNOWN = -1                                                # self of a function reached without a known caller

    def interp(addr, slf, oth, root, depth):
        """Linear walk of one function; slf/oth are symbol indexes of NPC instances (hero_i for Marvin);
        root = the dialogue's own npc (what `self` is again inside a choice function)."""
        if addr is None or addr not in fend: return
        key = (addr, slf, oth)
        if key in seen or depth > 8: return
        seen.add(key); reached.add(addr)
        pushes = []; pc = addr; end = fend[addr]
        while pc < end:
            op = code[pc]
            if op in OPERAND4:
                arg = struct.unpack_from("<i", code, pc + 1)[0]; pc += 5
                if op in (OP_PUSHINT, OP_PUSHVAR, OP_PUSHINST): pushes.append((op, arg)); continue
                if op == OP_CALLEXT:
                    if arg == ai_output and len(pushes) >= 3:
                        a, _, s = pushes[-3], pushes[-2], pushes[-1]
                        who = {self_i: slf, other_i: oth, hero_i: hero_i}.get(a[1], a[1]) if a[0] == OP_PUSHINST else None
                        if s[0] == OP_PUSHVAR and syms[s[1]]["type"] == T_STRING and syms[s[1]]["val"] and who is not None and who != UNKNOWN:
                            result[syms[s[1]]["val"][0].upper() + ".WAV"][npc_name(who)] += 1
                    elif arg == info_addchoice and pushes and pushes[-1][0] == OP_PUSHINT:
                        fn = pushes[-1][1]                          # choice function: runs with self = the dialogue's npc
                        if fn < len(syms) and syms[fn]["type"] == T_FUNC: queue.append((syms[fn]["val"], root, hero_i, root, 0))
                    pushes = []
                elif op == OP_CALL:
                    if arg == tria_next and pushes and pushes[-1][0] == OP_PUSHINST:
                        x = pushes[-1][1]; slf = {self_i: slf, other_i: oth, hero_i: hero_i}.get(x, x); oth = hero_i
                    elif arg == ai_function and len(pushes) >= 2 and pushes[-2][0] == OP_PUSHINST and pushes[-1][0] == OP_PUSHINT:
                        x, fn = pushes[-2][1], pushes[-1][1]
                        x = {self_i: slf, other_i: oth, hero_i: hero_i}.get(x, x)
                        if fn < len(syms) and syms[fn]["type"] == T_FUNC: queue.append((syms[fn]["val"], x, hero_i, root, 0))
                    else:
                        interp(arg, slf, oth, root, depth + 1)               # plain helper call: same self/other
                    pushes = []
                # jumps: fall through (linear walk)
            elif op == OP_PUSHARRAY: pc += 6
            else: pc += 1

    for info, fn in info_fn.items():
        if info in info_npc and fn < len(syms) and syms[fn]["type"] == T_FUNC: queue.append((syms[fn]["val"], info_npc[info], hero_i, info_npc[info], 0))
    while queue:
        a, s, o, r, d = queue.pop(); interp(a, s, o, r, d)
    n_dialog = len(reached)
    # functions no dialogue reaches (cutscenes, states, boards): walk them with an unknown self, so only explicit
    # speakers (an NPC instance or the hero) are recorded
    for a in funcs:
        if a not in reached: interp(a, UNKNOWN, UNKNOWN, UNKNOWN, 0)
    print(f"AI_Output sites resolved: {sum(sum(c.values()) for c in result.values())} on {len(result)} distinct wav names "
          f"({n_dialog} functions reached from dialogues, {len(reached) - n_dialog} others walked with unknown self)")

    # speaker token (the DIA_<TOKEN> owner we cast under) <-> NPC instances, from the C_INFO instance names
    tok_insts = collections.defaultdict(collections.Counter)
    for s in syms:
        if s["type"] == T_INSTANCE and s["i"] in info_npc:
            m = re.match(r"^(?:DIA|TRIA)_([^_]+)_", s["name"], re.I)
            if m: tok_insts[m.group(1).upper()][npc_name(info_npc[s["i"]])] += 1
    tok_insts["MARVIN"]["HERO"] += 1; tok_insts["MARVIN"]["PC_HERO"] += 1
    cast = {f[:-4].upper() for f in os.listdir(os.path.join(P, "refs", "cast")) if f.lower().endswith(".wav")}
    inst_tok = {}
    for tok, c in tok_insts.items():
        for inst, n in c.items():                   # prefer a cast token, then the most specific one (fewest instances), then most infos
            best = inst_tok.get(inst); score = (tok in cast, -len(c), n)
            if best is None or score > best[1]: inst_tok[inst] = (tok, score)
    def token(inst):
        if inst in inst_tok: return inst_tok[inst][0]
        m = re.match(r"^[A-Z]+_\d+_(.+)$", inst)   # chapter variants: NONE_10064_VOLKERGUARD_Q602 -> VOLKERGUARD
        if m:
            parts = m.group(1).split("_")
            for k in range(len(parts), 0, -1):
                if "_".join(parts[:k]) in cast: return "_".join(parts[:k])
        return "?" + inst
    with open(os.path.join(P, "work", "speaker_script.tsv"), "w", encoding="utf-8") as f:
        f.write("wav\tnpc_instance\tspeaker\tn_sites\tconflict\n")
        for w in sorted(result):
            c = result[w]; inst, n = c.most_common(1)[0]
            f.write(f"{w}\t{inst}\t{token(inst)}\t{sum(c.values())}\t{'|'.join(k for k in c if k != inst)}\n")
    # compare with the line sets: a line is fine when its filed token owns dialogues of the speaking instance
    for lf in line_files:
        if not os.path.exists(lf): continue
        rows = [l.rstrip("\n").split("\t") for l in open(lf, encoding="utf-8")][1:]
        bad = []; unknown = 0; nores = 0
        for r in rows:
            if len(r) < 2: continue
            w = r[1].upper(); c = result.get(w)
            if not c: nores += 1; continue
            inst = c.most_common(1)[0][0]; filed = r[0].upper()
            if inst in tok_insts.get(filed, {}): continue
            t = token(inst)
            if t == filed: continue
            if t.startswith("?"): unknown += 1
            bad.append((filed, t, w, r[2] if len(r) > 2 else ""))
        print(f"\n{os.path.basename(lf)}: {len(rows)} lines, {len(bad)} spoken by someone else, "
              f"{unknown} of those without a cast voice, {nores} not found in any function")
        pairs = collections.Counter((a, b) for a, b, _, _ in bad)
        for (a, b), n in pairs.most_common(): print(f"  filed under {a:10s} -> spoken by {b:14s} {n}")
        with open(lf.replace(".tsv", "_misattributed.tsv"), "w", encoding="utf-8") as f:
            f.write("filed_as\tspeaker\twav\ttext\n")
            for a, b, w, t in bad: f.write(f"{a}\t{b}\t{w}\t{t}\n")


if __name__ == "__main__":
    main()
