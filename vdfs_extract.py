r"""List or extract files from a Gothic VDFS archive (.vdf / .mod). The pipeline needs two files from your own install,
Data\KM_ScriptsEN.mod -> OU.BIN (dialogue text) and GOTHIC.DAT (compiled script: NPC genders, voices, who speaks what):
  python vdfs_extract.py "C:\...\TheChroniclesOfMyrtana\Data\KM_ScriptsEN.mod" --get OU.BIN GOTHIC.DAT
writes work/scripts/KM_ScriptsEN_OU.BIN and work/scripts/KM_ScriptsEN_GOTHIC.DAT (archive stem + file name).
usage: python vdfs_extract.py <archive> [--list] [--get NAME ...] [--out DIR]
"""
import os, struct, sys
P = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DIR, LAST = 0x80000000, 0x40000000


def entries(path):
    """Flat list of (name, offset, size) for every file entry (directories skipped)."""
    with open(path, "rb") as f:
        h = f.read(296)
        if b"PSVDSC_V2.00" not in h[256:272]: sys.exit("not a VDFS archive (missing PSVDSC_V2.00 signature)")
        n_entries, n_files, ts, size, root, esize = struct.unpack_from("<IIIIII", h, 272)
        f.seek(root); out = []
        for _ in range(n_entries):
            e = f.read(esize); name = e[:64].rstrip(b" \0").decode("latin-1")
            off, sz, typ, attr = struct.unpack_from("<IIII", e, 64)
            if not typ & DIR: out.append((name, off, sz))
    return out


def main():
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    arc = a[0]; want = []; out = os.path.join(P, "work", "scripts"); do_list = "--list" in a
    if "--get" in a:
        k = a.index("--get")
        for x in a[k + 1:]:
            if x.startswith("--"): break
            want.append(x)
    if "--out" in a: out = a[a.index("--out") + 1]
    ents = entries(arc)
    if do_list or not want:
        for name, off, sz in ents: print(f"{sz:>12}  {name}")
        print(f"{len(ents)} files"); return
    os.makedirs(out, exist_ok=True); stem = os.path.splitext(os.path.basename(arc))[0]
    with open(arc, "rb") as f:
        for w in want:
            hit = next(((n, o, s) for n, o, s in ents if n.upper() == w.upper()), None)
            if not hit: print(f"not in archive: {w}"); continue
            f.seek(hit[1]); data = f.read(hit[2]); dst = os.path.join(out, f"{stem}_{hit[0].upper()}")
            open(dst, "wb").write(data); print(f"{hit[0]} -> {dst} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
