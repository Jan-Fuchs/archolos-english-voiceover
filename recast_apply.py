"""Apply a chosen design from a casting round as a speaker's anchor, then re-render, QA and install that speaker's
chapter-1 lines. Old anchor kept as refs/cast/<SPK>.wav.bak-<time>. Records the choice in work/cast_overrides.tsv.
usage: python recast_apply.py SPK=out/jorn_design/B_same_desc_seed11.wav [SPK2=...] [--lines work/stage1_lines.tsv] [--pack]
"""
import os,sys,json,shutil,subprocess,time,re
P=os.path.dirname(os.path.abspath(__file__)); os.chdir(P); PY=sys.executable
args=[a for a in sys.argv[1:] if "=" in a]; lines_tsv=next((sys.argv[i+1] for i,a in enumerate(sys.argv) if a=="--lines"),"work/stage1_lines.tsv"); do_pack="--pack" in sys.argv
def run(*a):
    print(">>"," ".join(a),flush=True); r=subprocess.run([PY,*a],capture_output=True,text=True,encoding="utf-8",errors="replace"); print(r.stdout[-500:],r.stderr[-300:],flush=True)
ov="work/cast_overrides.tsv"
if not os.path.exists(ov): open(ov,"w",encoding="utf-8").write("speaker\tsource\tdescription\tdate\n")
spks=[]
for a in args:
    spk,src=a.split("=",1); spk=spk.upper(); spks.append(spk)
    stamp=time.strftime("%m%d-%H%M"); dst=f"refs/cast/{spk}.wav"
    if os.path.exists(dst): shutil.move(dst,f"{dst}.bak-{stamp}")
    shutil.copy(src,dst)
    key=os.path.splitext(os.path.basename(src))[0]; dj=os.path.join(os.path.dirname(src),"descriptions.json")
    desc=json.load(open(dj,encoding="utf-8")).get(key,"(current design)") if os.path.exists(dj) else ""
    rows=open("work/cast.tsv",encoding="utf-8").read().splitlines()
    for i,l in enumerate(rows):
        r=l.split("\t")
        if r[0].upper()==spk and len(r)>=10 and desc: r[8]=desc+f" [override {key}]"; rows[i]="\t".join(r)
    open("work/cast.tsv","w",encoding="utf-8").write("\n".join(rows)+"\n")
    open(ov,"a",encoding="utf-8").write(f"{spk}\t{src}\t{desc}\t{stamp}\n"); print("anchor set:",spk,"<-",src,flush=True)
st=open(lines_tsv,encoding="utf-8").read().splitlines(); redo=[l for l in st[1:] if l.split("\t")[0].upper() in spks]
open("work/redo_recast.tsv","w",encoding="utf-8").write("\n".join([st[0]]+redo)+"\n"); print("lines to re-render:",len(redo),flush=True)
run("render_all.py","--lines",lines_tsv,"--directions","work/batches/stage1_*.dir.tsv","--redo","work/redo_recast.tsv")
wavs={l.split("\t")[1].upper() for l in redo}
qa=open("work/qa_all.tsv",encoding="utf-8").read().splitlines(); open("work/qa_all.tsv","w",encoding="utf-8").write("\n".join(l for l in qa if l.split("\t")[0].upper() not in wavs)+"\n")
run("qa_all.py","--lines",lines_tsv); run("qa_refine.py")
inv="work/installed.txt"; keep=[]
for l in open(inv,encoding="utf-8").read().splitlines():
    if os.path.basename(l).upper() in wavs:
        if os.path.exists(l): os.remove(l)
    else: keep.append(l)
open(inv,"w",encoding="utf-8").write("\n".join(keep)+"\n")
run("install_stage.py","--lines",lines_tsv,"--skip-flagged")
if do_pack:
    running=b"Gothic2.exe" in subprocess.run(["tasklist","/FI","IMAGENAME eq Gothic2.exe"],capture_output=True).stdout
    if running: print("PACK PENDING (game running)",flush=True)
    else: run("pack_mod.py")
print("RECAST DONE",flush=True)
