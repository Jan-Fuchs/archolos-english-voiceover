"""Is the game running? Any Gothic2.exe with a real working set counts. Do NOT use the handle count: the game runs
with rights our scripts cannot read, so its handle count reads as 0 - which once let a repack rewrite the archives
under a running game (2026-10-03, dialogue pauses). A dead shell left after a crash holds only ~44 KB and is ignored."""
import re, subprocess


def game_running(min_kb=20000):
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Gothic2.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        p = [x.strip().strip('"') for x in line.split('","')]
        if len(p) >= 5 and p[0].lower().startswith("gothic2"):
            if int(re.sub(r"[^0-9]", "", p[4]) or 0) > min_kb: return True
    return False


if __name__ == "__main__":
    print("running" if game_running() else "not running")
