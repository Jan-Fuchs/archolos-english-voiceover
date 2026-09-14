# Archolos English voice-over — pipeline

Generates a directed, cast English voice-over for *The Chronicles of Myrtana: Archolos* with local models on one consumer
GPU (developed on an RTX 5070 Ti), and packs it as VDFS archives the game loads next to its own. Every voice is designed
from a text description — no real person's voice is cloned. Everything here was validated with blind listening rounds
(see "What mattered"). Status: chapter 1 dialogue and all 18,026 stock lines (every voice set) are done; chapters 2–6 next.

**What this repository is and is not.** It holds the pipeline only: scripts, the voice descriptions (`work\cast.tsv`),
the per-line delivery directions (`work\batches\`), and the measured findings. It holds **nothing from the game**: no
dialogue text, no extracted archives, no audio. Every text table is regenerated from *your own* installation in step 0.
The finished audio pack and the voice bank (the 619 designed anchor voices) are distributed separately (Nexus Mods), not here.

## Setup
- Python 3.12+ with `numpy`; `ffmpeg` on PATH (or `FFMPEG=<path>`); the game installed (`ARCHOLOS_DIR=<folder>` if not
  the default Steam path). Everything runs on Windows; the scripts use plain paths and should work elsewhere.
- Audio server: [audio.cpp](https://github.com/PABannier/audio.cpp) → put the build in `tools\audiocpp\` and run
  `tools\audiocpp\audiocpp_server.exe --config server.json --ui` → http://127.0.0.1:8080 (Arena tab for A/B).
- Models (`models\`, GGUF from Hugging Face, paths in `server.json`): **BreezeTTS 2 Q8** (production; English/Chinese only),
  **Qwen3-ASR 1.7B Q8** (QA round-trip + Polish transcripts); higgs / cosyvoice3 / qwen3-tts were experiments only.
  `max_loaded_models: 1`, so stages that alternate TTS and ASR swap models.
- **Step 0 — your own game data:** `python vdfs_extract.py "<game>\Data\KM_ScriptsEN.mod" --get OU.BIN GOTHIC.DAT`, then
  `python parse_ou.py` (→ `work\ou_lines.tsv`), `python npc_gender.py` (→ `work\gender_script.tsv`), `python who_speaks.py`
  (→ `work\speaker_script.tsv`). Voices: either drop the voice bank into `refs\cast\`, or run `cast_all.py` — it reuses the
  shipped descriptions with the same seed, so it re-creates the same cast on the same model.

## Data
- `work\ou_lines.tsv` — all 51,163 dialogue lines parsed from `Ou.bin` (ZenGin BIN_SAFE): block, wav name, text. Not in the repo.
  Filenames carry the dialogue OWNER (`DIA_<SPK>_…`), quest token (`Q203`, `SQ311`…; first digit = chapter), beat name, and `_15_` = Marvin.
  **The owner is not always the speaker**: in trialogues (`TRIA_Next(npc)`) and NPC-to-NPC scenes another NPC speaks under the owner's
  name, and the number before the index is whatever the writer typed (Riordian is `03`, so is Ezekiel). `who_speaks.py` walks every
  dialogue function in `GOTHIC.DAT` (self/other tracking through TRIA_Next, AI_Function, Info_AddChoice) and writes
  `work\speaker_script.tsv` (wav → NPC instance → cast token) plus `<lines>_misattributed.tsv` for a line set. Chapter 1 had 42 such
  lines (Jorn in Fabio's scenes, Viktor in Martha's, Dennis in Terry's …), fixed 2026-09-14. **Run it on every new line set before casting.**
- `work\stage1_lines.tsv` — chapter-1 line set (conversations of the 64 speakers with a chapter-1 quest line; `tier` = quest|filler).
  **Lesson:** select by conversation blocks of speakers *present in the chapter*, not by quest tokens only (prologue sailors were missed →
  `work\stage1b_lines.tsv`).

## Stages (run in this order)
1. **Casting — `cast_all.py`** (`.venv` python; needs numpy). For each speaker: ~15 s of their Polish lines → pitch (octave-corrected),
   jitter, spectral centroid, syllable rate → tercile bins relative to the whole cast → a one-sentence voice description with the accent
   pinned to native English (≈20% get a light regional accent, fixed per character by hash) → Breeze **voice design** speaking the
   character's own longest line → `refs\cast\<SPK>.wav` + `refs\cast\prompt_text`. Gender is read from `work\gender_llm.tsv`
   (LLM-judged from name + lines; pitch alone misgenders ~140 men). Marvin is fixed to design J. Resumable; `--only A,B`.
2. **Directions — `gen_directions.py`** — one line of delivery notes per wav, written by a chat model from the dialogue context alone
   (speaker, file name, ±2 lines of the conversation; the prompt is the `SYSTEM` string in the script). The speaker comes from the
   line set's `speaker` column (or `work\speaker_script.tsv`), never from the file name. Any model works — in blind rounds the writer
   model made no measurable difference (Opus 5 = Sonnet 5 = hand-written); the TTS take variance did. Three ways to run it:
   - **Anthropic key:** `set ANTHROPIC_API_KEY=…` then `python gen_directions.py --lines <tsv> --out work\batches\<name>.dir.tsv`
     (`--model claude-opus-5` default, `--effort medium`).
   - **OpenAI-style key or any OpenAI-compatible server** (OpenAI, OpenRouter, Ollama, LM Studio, llama.cpp): `set OPENAI_API_KEY=…`,
     optionally `set OPENAI_BASE_URL=http://localhost:11434/v1`, then the same command with `--model <name>` (`--provider openai` to force).
   - **No key:** `--dump <ctx.txt>` writes the system prompt plus every line with its context; give each ≤150-line file to a fresh chat
     (any assistant) with: *"Read the file, follow the SYSTEM PROMPT, write one direction per `###` heading in order to `<name>.dir.tsv`
     (wav<TAB>instruction), reply with the row count."* **This is how all directions in this repo were written:** no API key, just a
     Claude subscription — Claude Code spawned one subagent per ctx file and they wrote the TSVs directly.
   Validate: every row matches a heading, no identical instructions across batches, nothing asking for sighs/breaths (Breeze can't).
   `work\batches\` already ships the directions for chapter 1 and every stock line.
3. **Render — `render_all.py --lines <tsv> --directions "work\batches\*.dir.tsv"`** — Breeze, `voice_ref` = anchor, `reference_text`
   = the anchor's line, `instruction` = the direction (fallback: tier default), guidance 3.5, deterministic seed per filename.
   ~2.3 s/line. `--redo <tsv with wav column> --seed-offset N` re-takes specific lines.
4. **QA — `qa_all.py --lines <tsv>` then `qa_refine.py`** — Qwen3-ASR round-trip vs source (numbers spelled out, homophones forgiven;
   WER ≥ 0.6 on lines of 4+ words), duration ratio vs the Polish original outside 0.25–2.5×. Re-take flagged lines once; whatever fails
   twice is left to the pack.
5. **Install — `install_stage.py --lines <tsv> --skip-flagged [--adpcm]`** → 44.1 kHz mono loose files in `_work\Data\Sound\Speech\`
   (inventory `work\installed.txt`; `--uninstall`). `--adpcm` writes 4-bit IMA ADPCM, the game's own speech format, at a quarter of
   the PCM size — use it for a release build. Then **`pack_mod.py`** → `Data\KM_SpeechJAN1.mod`, `KM_SpeechJAN2.mod`, … (VDFS,
   timestamp 2099-01-01 — newest archive wins; **each under 1.5 GB** because the engine reads 32-bit signed offsets and entries past
   2 GiB are silent) and registers them on the ini `[FILES] vdf=` line. **The game must be closed** to rewrite the archives.

## Stock lines (SVM_<voice>_*.WAV)
Keyed by the NPC's `C_NPC.voice` (74 sets; the number in a DIA filename is the NPC *id*, not the voice). `npc_gender.py` reads
voice, id and MALE/FEMALE per NPC from `work\scripts\KM_ScriptsEN_GOTHIC.DAT`. `work\svm_voices.tsv` maps each set to the
designed voice of its main named speaker. Directions are written once per distinct (token, text) and reused across sets.
**Run everything:** `.venv\Scripts\python svm_run.py` (resumable; status in `work\svm_run.status`; packs when the game is closed).
Grunts ("Aargh") and stage notes ("<hearty yawn>") are left to the pack. Per-character recasts: `recast_apply.py SPK=<design.wav> --pack`.

## What mattered (blind rounds)
1. Every line directed (+0.9 over the original pack on identical voices). Model without direction lost to the pack.
2. Casting by description, not cloning: fits the character, no accidental accent, costs nothing in preference.
3. Pacing as a rule: unhurried by default; speed only when the character is plainly impatient.
4. Writer model didn't matter (Opus 5 = Sonnet 5 = Fable 5.1 = hand-written). Per-take variance did → QA + re-takes.
5. Tempo: rendered words/sec jumps >1.5× between adjacent lines of one speaker in 24% of pairs even with identical pace directions
   (Breeze take variance). Candidate fixes under test on the ship demo: whole-conversation directions (`work\demo\ship_v2.ctx.txt`)
   and `consistency_pick.py` (K takes per line, pick the steady one). Breeze cannot render sighs/breaths — never ask for them.
   Conversation order = trailing `_NN` index of the file name, not Ou.bin file order.

## Revert
Delete `Data\KM_SpeechJAN*.mod`, remove them from `system\TheChroniclesOfMyrtana.ini` (`vdf=` line), run `python install_stage.py --uninstall`.

## License
The code is MIT (see `LICENSE`). The voice-over audio is an adaptation of *The Chronicles of Myrtana: Archolos*, released by its
team under the GothicMOD license (Archolos EULA, Annex B; German original of the relevant clauses in `GothicMOD_Lizenz_Auszug.txt`):
non-commercial, same license for adaptations, own title, and — as the license requires for altered works — the original authors are
credited as *basierend auf einem Werk von The Chronicles of Myrtana Team* rather than listed as authors of this version.
This is a fan project, not endorsed by the Archolos team.
