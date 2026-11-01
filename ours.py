"""Switch our voice-over archives on or off (for A/B against the old pack). Game must be closed.
The ini line alone does nothing (SystemPack loads every Data\\*.mod), so "off" also MOVES KM_SpeechJAN*.mod from Data\\
to Data_JAN_off\\ (same drive, instant) and "on" moves them back.
usage: python ours.py off | on | status"""
import glob, os, re, sys
from gamecheck import game_running
GAME = os.environ.get("ARCHOLOS_DIR", r"C:\Program Files (x86)\Steam\steamapps\common\TheChroniclesOfMyrtana")
INI = os.path.join(GAME, "system", "TheChroniclesOfMyrtana.ini")
DATA, OFF = os.path.join(GAME, "Data"), os.path.join(GAME, "Data_JAN_off")
s = open(INI, encoding="latin-1").read(); m = re.search(r"^vdf=(.*)$", s, re.M); vols = m.group(1).split()
cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
if cmd in ("on", "off") and game_running(): sys.exit("close the game first")
ours = sorted((os.path.basename(p) for p in glob.glob(os.path.join(OFF, "KM_SpeechJAN*.mod")) + glob.glob(os.path.join(DATA, "KM_SpeechJAN*.mod"))),
              key=lambda n: int(re.sub(r"\D", "", n)))
if cmd == "off":
    vols = [v for v in vols if not v.startswith("KM_SpeechJAN")]
    os.makedirs(OFF, exist_ok=True)
    for p in glob.glob(os.path.join(DATA, "KM_SpeechJAN*.mod")): os.replace(p, os.path.join(OFF, os.path.basename(p)))
if cmd == "on":
    vols = [v for v in vols if not v.startswith("KM_SpeechJAN")] + ours
    for p in glob.glob(os.path.join(OFF, "KM_SpeechJAN*.mod")): os.replace(p, os.path.join(DATA, os.path.basename(p)))
if cmd in ("on", "off"): open(INI, "w", encoding="latin-1").write(s[: m.start(1)] + "  ".join(vols) + s[m.end(1):])
inside = sorted(os.path.basename(p) for p in glob.glob(os.path.join(DATA, "KM_SpeechJAN*.mod")))
print("ours", "ON" if inside else "OFF", "| in Data:", inside or "none", "| vdf=", "  ".join(vols))
