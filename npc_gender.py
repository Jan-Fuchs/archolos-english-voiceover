"""Definitive NPC gender from the compiled Daedalus script (GOTHIC.DAT): every NPC instance calls
B_SetNpcVisual(self, MALE|FEMALE, ...) or sets a body mesh (hum_body_Naked* = man, Hum_Body_Babe* = woman).
Maps dialogue speaker tokens (DIA_<SPK>_...) to NPC instances through the C_INFO instances' `npc` field.
output: work/gender_script.tsv (speaker, gender, source, npc_instance) and a comparison with work/gender_llm.tsv
usage: python npc_gender.py [work/scripts/KM_ScriptsEN_GOTHIC.DAT]
"""
import os, re, struct, sys, collections
P = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
T_FLOAT, T_INT, T_STRING, T_CLASS, T_FUNC, T_PROTOTYPE, T_INSTANCE = 1, 2, 3, 4, 5, 6, 7
F_CONST, F_CLASSVAR, F_EXTERNAL = 1, 4, 8
OPERAND4 = {61, 62, 64, 65, 67, 75, 76, 80}          # CALL, CALLEXTERNAL, PUSHINT, PUSHVAR, PUSHINST, JUMP, JUMPF, SETINSTANCE
OP_RET, OP_CALL, OP_CALLEXT, OP_PUSHINT, OP_PUSHVAR, OP_PUSHINST, OP_PUSHARRAY = 60, 61, 62, 64, 65, 67, 245


def cstr(b, i):
    j = b.index(b"\n", i); return b[i:j].decode("latin-1"), j + 1   # .dat strings end with a newline, not NUL


def load(path):
    b = open(path, "rb").read(); i = 0
    ver = b[i]; i += 1
    n = struct.unpack_from("<I", b, i)[0]; i += 4
    i += 4 * n                                       # sort table
    syms = []
    for k in range(n):
        named = struct.unpack_from("<I", b, i)[0]; i += 4
        name = ""
        if named: name, i = cstr(b, i)
        off, bits, filenr, line, lc, cs, cc = struct.unpack_from("<iIIiiii", b, i); i += 28
        count = bits & 0xFFF; typ = (bits >> 12) & 0xF; flags = (bits >> 16) & 0x3F
        val = None
        if not flags & F_CLASSVAR:
            if typ == T_FLOAT: val = list(struct.unpack_from(f"<{count}f", b, i)); i += 4 * count
            elif typ == T_INT: val = list(struct.unpack_from(f"<{count}i", b, i)); i += 4 * count
            elif typ == T_STRING:
                val = []
                for _ in range(count): s, i = cstr(b, i); val.append(s)
            elif typ in (T_CLASS, T_FUNC, T_PROTOTYPE, T_INSTANCE): val = struct.unpack_from("<i", b, i)[0]; i += 4
        parent = struct.unpack_from("<i", b, i)[0]; i += 4
        syms.append({"i": k, "name": name, "type": typ, "flags": flags, "count": count, "val": val, "parent": parent, "off": off})
    size = struct.unpack_from("<I", b, i)[0]; i += 4
    code = b[i:i + size]
    return syms, code


def walk(code, addr, syms, limit=20000):
    """Yield (pc, op, operand) from addr until RET (or a jump past a RET guard)."""
    pc = addr; n = 0
    while pc < len(code) and n < limit:
        op = code[pc]; n += 1
        if op in OPERAND4:
            arg = struct.unpack_from("<i", code, pc + 1)[0]; yield pc, op, arg; pc += 5
        elif op == OP_PUSHARRAY:
            arg = struct.unpack_from("<i", code, pc + 1)[0]; yield pc, op, arg; pc += 6
        else:
            yield pc, op, None; pc += 1
        if op == OP_RET: return


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(P, "work", "scripts", "KM_ScriptsEN_GOTHIC.DAT")
    syms, code = load(path)
    byname = {s["name"].upper(): s for s in syms if s["name"]}
    print(f"{len(syms)} symbols, {len(code)} bytes of code")
    cls_npc = byname["C_NPC"]["i"]; cls_info = byname["C_INFO"]["i"]
    setvis = byname.get("B_SETNPCVISUAL"); setvis_addr = setvis["val"] if setvis else None
    npc_field = byname.get("C_INFO.NPC"); npc_field_i = npc_field["i"] if npc_field else None
    male = byname.get("MALE", {}).get("val", [0])[0]; female = byname.get("FEMALE", {}).get("val", [1])[0]
    print("B_SetNpcVisual at", setvis_addr, "| C_INFO.npc symbol", npc_field_i, "| MALE", male, "FEMALE", female)
    # 1. gender (+ id, voice) per NPC instance; instances usually derive from a prototype (NPC_DEFAULT), so resolve the root class
    def root_class(s):
        p = s["parent"]
        while p >= 0 and syms[p]["type"] == T_PROTOTYPE: p = syms[p]["parent"]
        return p
    npcs = [s for s in syms if s["type"] == T_INSTANCE and root_class(s) == cls_npc]
    gender = {}; npc_voice = {}; npc_id = {}
    voice_field = byname.get("C_NPC.VOICE", {}).get("i"); id_field = byname.get("C_NPC.ID", {}).get("i")
    def parent_chain(s):                                  # instance code first, then its prototypes
        out = [s["val"]]; p = s["parent"]
        while p >= 0 and syms[p]["type"] == T_PROTOTYPE: out.append(syms[p]["val"]); p = syms[p]["parent"]
        return out
    src_count = collections.Counter()
    for s in npcs:
        g = None; src = ""; nm = s["name"].upper()
        for addr in parent_chain(s):
            pushes = []; last_int = None
            for pc, op, arg in walk(code, addr, syms):
                if op == OP_PUSHINT: pushes.append(("int", arg)); last_int = arg
                elif op == OP_PUSHVAR or op == OP_PUSHINST or op == OP_PUSHARRAY:
                    t = syms[arg] if 0 <= arg < len(syms) else None
                    if op == OP_PUSHVAR and arg == voice_field and last_int is not None and nm not in npc_voice: npc_voice[nm] = last_int
                    if op == OP_PUSHVAR and arg == id_field and last_int is not None and nm not in npc_id: npc_id[nm] = last_int
                    if t and t["type"] == T_INT and t["flags"] & F_CONST and t["val"]: pushes.append(("int", t["val"][0])); last_int = t["val"][0]
                    elif t and t["type"] == T_STRING and t["val"]:
                        v = t["val"][0].upper(); pushes.append(("str", v))
                        if "HUM_BODY_BABE" in v and g is None: g, src = "woman", "body mesh"
                        elif "HUM_BODY_NAKED" in v and g is None: g, src = "man", "body mesh"
                    else: pushes.append(("sym", arg))
                elif op == OP_CALL and arg == setvis_addr and len(pushes) >= 6:
                    a = pushes[-5]
                    if a[0] == "int" and g is None: g, src = ("woman" if a[1] == female else "man"), "B_SetNpcVisual"
                elif op == OP_CALL or op == OP_CALLEXT: pushes = pushes[-16:]
            if g and nm in npc_voice: break
        if g: gender[nm] = (g, src); src_count[src] += 1
    print(f"NPC instances: {len(npcs)}, gender resolved for {len(gender)} ({dict(src_count)}), voice known for {len(npc_voice)}")
    # 2. speaker token -> NPC via C_INFO instances (DIA_*)
    infos = [s for s in syms if s["type"] == T_INSTANCE and root_class(s) == cls_info]
    tok_npc = collections.defaultdict(collections.Counter)
    for s in infos:
        m = re.match(r"^(?:DIA|TRIA)_([^_]+)_", s["name"], re.I)
        if not m: continue
        tok = m.group(1).upper(); last = None
        for pc, op, arg in walk(code, s["val"], syms):
            if op in (OP_PUSHINT, OP_PUSHVAR, OP_PUSHINST):
                if op == OP_PUSHVAR and arg == npc_field_i:
                    if last is not None and 0 <= last < len(syms) and syms[last]["type"] == T_INSTANCE: tok_npc[tok][syms[last]["name"].upper()] += 1
                else: last = arg
    # 3. combine
    out = {}
    for tok, c in tok_npc.items():
        votes = collections.Counter()
        for npc, n in c.items():
            if npc in gender: votes[gender[npc][0]] += n
        if votes:
            g = votes.most_common(1)[0][0]; npc = c.most_common(1)[0][0]
            out[tok] = (g, "script", npc, dict(votes), npc_voice.get(npc), npc_id.get(npc))
    print(f"speaker tokens with a script gender: {len(out)} of {len(tok_npc)} dialogue tokens")
    with open(os.path.join(P, "work", "gender_script.tsv"), "w", encoding="utf-8") as f:
        f.write("speaker\tgender\tsource\tnpc_instance\tvotes\tvoice\tid\n")
        for tok, (g, src, npc, votes, voice, nid) in sorted(out.items()): f.write(f"{tok}\t{g}\t{src}\t{npc}\t{votes}\t{voice}\t{nid}\n")
    st1_tokens = set()
    p1 = os.path.join(P, "work", "stage1_lines.tsv")
    if os.path.exists(p1): st1_tokens = {l.split("\t")[0] for l in open(p1, encoding="utf-8").read().splitlines()[1:]}
    vc = collections.Counter(out[t][4] for t in out if t in st1_tokens and out[t][4] is not None)
    print("SVM voice sets used by chapter-1 speakers (voice: #speakers):", sorted(vc.items(), key=lambda x: -x[1]))
    print("voice of EZEKIEL/FLORA/JORN/VRAZKA:", {t: out.get(t, (None,) * 5)[4] for t in ("EZEKIEL", "FLORA", "JORN", "VRAZKA")})
    # 4. compare with the LLM pass
    llm = {}
    p = os.path.join(P, "work", "gender_llm.tsv")
    if os.path.exists(p):
        for l in open(p, encoding="utf-8").read().splitlines()[1:]:
            r = l.split("\t")
            if len(r) >= 2: llm[r[0].upper()] = r[1].strip().lower()
    st1 = set()
    p1 = os.path.join(P, "work", "stage1_lines.tsv")
    if os.path.exists(p1): st1 = {l.split("\t")[0] for l in open(p1, encoding="utf-8").read().splitlines()[1:]}
    diff = [(t in st1, t, llm[t], out[t][0], out[t][2]) for t in out if t in llm and llm[t] != out[t][0]]
    diff.sort(key=lambda x: (not x[0], x[1]))
    print(f"LLM vs script disagreements: {len(diff)} of {sum(1 for t in out if t in llm)} compared; chapter-1: {sum(1 for d in diff if d[0])}")
    for c1, t, a, b, npc in diff: print(f"  {'ch1 ' if c1 else '    '}{t:18s} llm={a:5s} script={b:5s}  ({npc})")
    print("unresolved tokens (no NPC or no gender):", sorted(set(tok_npc) - set(out))[:20])
    for t in ("VRAZKA", "FLORA", "JORN", "MAIWEN", "SVEN", "IVAN", "FRED", "MALEN", "TESPI"):
        print("  check", t, out.get(t, ("?",))[0], tok_npc.get(t, {}))


if __name__ == "__main__":
    main()
