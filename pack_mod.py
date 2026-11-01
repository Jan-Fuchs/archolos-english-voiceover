"""Pack installed lines (work/installed.txt -> the 44.1 kHz files) into VDFS .mod archives that outrank every other
archive (DOS timestamp 2099-01-01), drop them into the game's Data folder and register them in the mod ini [FILES] line.
The engine reads archives with 32-bit signed offsets, so each archive stays under LIMIT bytes (entries beyond 2 GiB
were silent in-game). Archives: KM_SpeechJAN1.mod, KM_SpeechJAN2.mod, ... Stale higher-numbered ones are removed."""
import os, re, struct, subprocess, sys, time
P = os.path.dirname(os.path.abspath(__file__))
GAME = os.environ.get("ARCHOLOS_DIR", "C:/Program Files (x86)/Steam/steamapps/common/TheChroniclesOfMyrtana")
LIMIT = 1_500_000_000
def dos_ts(y, mo, d, h=0, mi=0): return ((((y - 1980) << 9) | (mo << 5) | d) << 16) | ((h << 11) | (mi << 5))

from gamecheck import game_running
if game_running():                                           # never write the archives under a running game (see gamecheck.py)
    sys.exit("Gothic2.exe is running - close the game first (the game reads archive offsets once at startup)")
files = [l.strip() for l in open(os.path.join(P, "work", "installed.txt"), encoding="utf-8") if l.strip() and os.path.exists(l.strip())]
files = sorted({os.path.basename(f).upper(): f for f in files}.items())          # unique by name, alphabetical
sizes = {n: os.path.getsize(p) for n, p in files}
chunks, cur, cur_bytes = [], [], 0
for n, p in files:
    if cur and cur_bytes + sizes[n] + 80 * (len(cur) + 5) + 296 > LIMIT:
        chunks.append(cur); cur, cur_bytes = [], 0
    cur.append((n, p)); cur_bytes += sizes[n]
if cur: chunks.append(cur)

def write_archive(name, chunk):
    dirs = ["_WORK", "DATA", "SOUND", "SPEECH"]
    n_entries = len(dirs) + len(chunk); cat_end = 296 + 80 * n_entries
    entries = [(d, i + 1, 0, 0x80000000 | 0x40000000, 0) for i, d in enumerate(dirs)]   # each dir: sole entry of its level
    off = cat_end
    for k, (n, p) in enumerate(chunk):
        entries.append((n, off, sizes[n], 0x40000000 if k == len(chunk) - 1 else 0, 0x20)); off += sizes[n]
    comment = (name + "\nArcholos English voice-over (Jan's pipeline)\n").encode("latin-1")
    header = comment + bytes([0x1A]) * (256 - len(comment)) + b"PSVDSC_V2.00\n\r\n\r" + struct.pack("<6I", n_entries, len(chunk), dos_ts(2099, 1, 1), sum(sizes[n] for n, _ in chunk), 296, 0x50)
    out = os.path.join(GAME, "Data", name); t0 = time.time()
    with open(out, "wb") as f:
        f.write(header)
        for n, o, sz, flag, attr in entries:
            f.write(n.encode("latin-1").ljust(64, b" ") + struct.pack("<4I", o, sz, flag, attr))
        for _, p in chunk:
            with open(p, "rb") as src:
                while True:
                    b = src.read(8 << 20)
                    if not b: break
                    f.write(b)
    total = os.path.getsize(out)
    with open(out, "rb") as f:   # verify with the strict reader shape used on the English pack
        f.seek(256); sig = f.read(16); ne, nf, ts, ds, ro, ver = struct.unpack("<6I", f.read(24)); f.seek(ro)
        ents = [f.read(80) for _ in range(ne)]; last = struct.unpack_from("<4I", ents[-1], 64); f.seek(last[0]); magic = f.read(4)
    ok = sig == b"PSVDSC_V2.00\n\r\n\r" and magic == b"RIFF" and last[0] + last[1] == total and total < 2**31
    print(f"wrote {name}: {len(chunk)} files, {total/1e9:.2f} GB, {chunk[0][0]} .. {chunk[-1][0]}, {time.time()-t0:.0f}s, verify={'ok' if ok else 'FAILED'}")
    if not ok: sys.exit(1)
    return name

names = [write_archive(f"KM_SpeechJAN{i}.mod", c) for i, c in enumerate(chunks, 1)]
for f in os.listdir(os.path.join(GAME, "Data")):                                  # remove stale higher-numbered archives
    if re.fullmatch(r"KM_SpeechJAN\d+\.mod", f, re.I) and f not in names:
        os.remove(os.path.join(GAME, "Data", f)); print("removed stale", f)
ini = os.path.join(GAME, "system", "TheChroniclesOfMyrtana.ini"); s = open(ini, "rb").read().decode("latin-1")
lines = s.split("\r\n")
for i, l in enumerate(lines):
    if l.lower().startswith("vdf="):
        toks = [t for t in l[4:].split() if not t.upper().startswith("KM_SPEECHJAN")]
        lines[i] = "vdf=" + "  ".join(toks + names)
open(ini, "wb").write("\r\n".join(lines).encode("latin-1"))
print("ini:", [l for l in lines if l.lower().startswith("vdf=")][0])
