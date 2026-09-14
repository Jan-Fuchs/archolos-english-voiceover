r"""Parse the game's OU.BIN (ZenGin BIN_SAFE cutscene library) into work/ou_lines.tsv: block, wav, text.
Every dialogue line the game can play is one oCMsgConversation with `name` (the wav file) and `text` (the subtitle),
inside a zCCSBlock whose `blockName` is the conversation beat. This is the text table every other script reads.
Get OU.BIN from your own install first: python vdfs_extract.py "<game>\Data\KM_ScriptsEN.mod" --get OU.BIN GOTHIC.DAT
usage: python parse_ou.py [work/scripts/KM_ScriptsEN_OU.BIN] [--out work/ou_lines.tsv]
"""
import os, struct, sys
P = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FIXED = {2: 4, 3: 4, 4: 1, 5: 2, 6: 4, 7: 12, 8: 4, 0xC: 4, 0x10: 4, 0x11: 4, 0x12: 4}   # int float byte word bool vec3 color enum hash ... hashkey
VARLEN = {1, 9, 0xA}                                                                # string raw rawfloat: u16 length + bytes


def main():
    args = sys.argv[1:]
    out = os.path.join(P, "work", "ou_lines.tsv")
    if "--out" in args: k = args.index("--out"); out = args[k + 1]; del args[k:k + 2]
    src = args[0] if args else os.path.join(P, "work", "scripts", "KM_ScriptsEN_OU.BIN")
    b = open(src, "rb").read()
    i = b.index(b"END\n") + 4
    if b"BIN_SAFE" not in b[:i]: sys.exit("not a BIN_SAFE archive")
    ver, nobj, hoff = struct.unpack_from("<III", b, i); i += 12
    keys = {}; j = hoff; cnt = struct.unpack_from("<I", b, j)[0]; j += 4             # property-name table at the end
    for _ in range(cnt):
        klen, idx, h = struct.unpack_from("<HHI", b, j); j += 8
        keys[idx] = b[j:j + klen].decode("latin-1"); j += klen
    rows = []; block = text = name = key = None
    while i < hoff:
        t = b[i]; i += 1
        if t in VARLEN:
            n = struct.unpack_from("<H", b, i)[0]; i += 2; raw = b[i:i + n]; i += n
            if t == 1:
                s = raw.decode("cp1252", "replace")
                if s.startswith("[% zCCSBlock "): block = text = name = None
                elif key == "blockName": block = s
                elif key == "text": text = s
                elif key == "name" and s.upper().endswith(".WAV"): rows.append((block or "", s, text or ""))
            key = None
        elif t == 0x12: key = keys.get(struct.unpack_from("<I", b, i)[0]); i += 4
        elif t in FIXED: i += FIXED[t]; key = None
        else: sys.exit(f"unknown BIN_SAFE chunk type {t:#x} at offset {i - 1}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("block\twav\ttext\n")
        for r in rows: f.write("\t".join(x.replace("\t", " ").replace("\n", " ") for x in r) + "\n")
    print(f"{len(rows)} lines ({nobj} objects, {len(keys)} property names) -> {out}")


if __name__ == "__main__":
    main()
