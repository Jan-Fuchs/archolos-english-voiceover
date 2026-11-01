# Archolos English voice-over — pipeline

Generates a directed, cast English voice-over for *The Chronicles of Myrtana: Archolos* with local models on one consumer
GPU (developed on an RTX 5070 Ti), and packs it as VDFS archives the game loads next to its own. Every voice is designed
from a text description — no real person's voice is cloned. Everything here was validated with blind listening rounds
(see "What mattered").

**Status: finished.** The whole game is voiced: 50,802 of the game's 50,900 speech files (99.8%) — all dialogue of
chapters 1–6 and all 74 stock-line voice sets, in about 620 designed voices, packed as three archives (~4.4 GB). The other
98 play from whatever speech archives are installed: 83 lines that failed QA after five takes, and 15 animal and orc sounds.

**What this repository is and is not.** It holds the pipeline only: scripts, the voice descriptions (`work\cast.tsv`),
the per-line delivery directions (`work\batches\*.dir.tsv`), and the measured findings. It holds **nothing from the game**:
no dialogue text, no extracted archives, no audio. Every text table is regenerated from *your own* installation in step 0.
The finished audio pack and the voice bank (the designed anchor voices) are distributed separately (Nexus Mods), not here.

## Playing with it
- **Sound settings (required).** In `system\Gothic.ini`, section `[ENGINE]`: `zSndCacheSizeMaxBytes=150000000` and
  `zSndCacheOutTimeMSec=600000`; in the game's audio options, sample rate 44 kHz. With the defaults (20 MB, 10 s, 22 kHz)
  the engine drops lines in longer conversations: subtitle without voice, 8-second holds, a hiss that builds up. The
  original English pack fails the same way, so this is the engine, not the files. Both settings were changed together and
  fixed it; a Steam "verify files" or an ini reset reverts them.
- The archives go to `Data\KM_SpeechJAN1.mod` … (timestamp 2099-01-01, so they outrank every other speech archive).
  The game loads every `Data\*.mod` regardless of the ini `vdf=` line; `python ours.py off | on | status` moves ours out of
  `Data\` and back for an A/B against another pack.

## Setup
- Python 3.12+ with `numpy` (`.venv`); `ffmpeg` on PATH (or `FFMPEG=<path>`); the game installed (`ARCHOLOS_DIR=<folder>`
  if not the default Steam path). Everything runs on Windows; the scripts use plain paths and should work elsewhere.
- Checks that need neural models run on CPU in a second venv, `.venv-audit` (torch, torchaudio, speechbrain, transformers,
  soundfile): `audit_audio.py`, `recast_auto.py`, `anchor_bench.py`, `gender_lines.py`, `pick_gender_take.py`, `stage_extra_cast.py`.
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
- `work\ou_lines.tsv` — every dialogue line parsed from `Ou.bin` (ZenGin BIN_SAFE): block, wav name, text; 50,900 distinct
  speech files. Not in the repo. Filenames carry the dialogue OWNER (`DIA_<SPK>_…`), quest token (`Q203`, `SQ311`…; first
  digit = chapter), beat name, and `_15_` = Marvin. Conversation order = trailing `_NN` index, not Ou.bin file order.
- **The owner is not always the speaker**: in trialogues (`TRIA_Next(npc)`) and NPC-to-NPC scenes another NPC speaks under
  the owner's name, and the number before the index is whatever the writer typed (Riordian is `03`, so is Ezekiel).
  `who_speaks.py` walks every dialogue function in `GOTHIC.DAT` (self/other tracking through TRIA_Next, AI_Function,
  Info_AddChoice) and writes `work\speaker_script.tsv` (wav → NPC instance → cast token). Run it before casting or rendering.
- **Gender comes from the compiled script** (`npc_gender.py`: the MALE/FEMALE argument of each NPC's `B_SetNpcVisual`),
  merged into `work\gender_llm.tsv` with an LLM judgement from name and lines for the rest. Never judge gender from the
  token: the modders reused names (`OLAF` is Helga, `GASPAR` is Rita), and pitch alone misgendered ~130 men.
- Stock lines (`SVM_<voice>_*.WAV`) are keyed by the NPC's `C_NPC.voice` (74 sets; the number in a DIA filename is the
  NPC *id*, not the voice). `work\svm_voices.tsv` maps each set to the designed voice of its main named speaker.
- `work\stage1_lines.tsv` — the chapter-1 line set; `build_rest.py` builds the line sets for everything not yet installed
  (`work\rest_<block>_lines.tsv`, blocks 1, 2, world, 3, 4, 5, 6 by chapter) and lists lines whose speaker has no voice in
  `work\rest_unvoiced.tsv`.

## Stages
1. **Casting — `cast_all.py`.** For each speaker: ~15 s of their Polish lines → pitch (octave-corrected), jitter, spectral
   centroid, syllable rate → tercile bins relative to the whole cast → a one-sentence voice description with the accent
   pinned to native English (≈20% get a light regional accent, fixed per character by hash) → Breeze **voice design**
   speaking the character's own longest line → `refs\cast\<SPK>.wav` + `refs\cast\prompt_text`. Marvin is fixed to design J.
   Resumable; `--only A,B`.
   **Checks — `recast_auto.py SPK1,SPK2 [--apply]`** designs several seeds per character and keeps the candidate that is heard
   as the right gender (wav2vec2 classifier), stays distinct from the rest of the cast (ECAPA similarity penalised above 0.5,
   where different human actors of the Polish cast stay below), and has a lively melody; `anchor_bench.py SPK --lines …` builds a blind page (current / livelier / new design) for one character;
   `recast_apply.py SPK=<wav> --lines <set> [--pack]` installs a chosen anchor and re-renders that speaker's lines.
   Every recast is logged in `work\cast_overrides.tsv`.
2. **Directions** — one line of delivery notes per wav, written by a chat model.
   - **`make_scenes.py --lines <tsv> --prefix work\batches\<name>`** (used for everything after chapter 1 and all fixes):
     whole scenes in true spoken order, choice branches as separate alternatives after their opening (dialogue is a tree),
     the real speaker per line, lines that already have a direction shown with it. Writes `<name>_NN.ctx.txt` (≤150 target
     lines each) + `<name>_NN.targets.tsv`; give each ctx file to a fresh chat or subagent, which writes `<name>_NN.dir.tsv`
     (wav<TAB>instruction); `make_scenes.py --check work\batches\<name>` validates every batch.
   - **`gen_directions.py`** (chapter 1): ±2 lines of context per line, with an API key (`ANTHROPIC_API_KEY`, or
     `OPENAI_API_KEY` + optional `OPENAI_BASE_URL` for any OpenAI-compatible server) or `--dump <ctx.txt>` for a chat.
   All directions in this repo were written without an API key: Claude Code spawned one subagent per ctx file on a Claude
   subscription. In blind rounds the writer model made no measurable difference. Breeze can't render sighs or breaths, so
   directions never ask for them; grunts work only when written as text ("Argh!") with a direction that shapes them.
3. **Render — `render_all.py --lines <tsv> --directions "work\batches\*.dir.tsv"`** — Breeze, `voice_ref` = anchor,
   `reference_text` = the anchor's line, `instruction` = the direction, guidance 3.5, deterministic seed per filename.
   ~2.3 s/line (~33 h for the whole game). `--redo <tsv with wav column> --seed-offset N` re-takes specific lines.
4. **QA — `qa_all.py --lines <tsv>` then `qa_refine.py`** — Qwen3-ASR round-trip vs source (numbers spelled out,
   homophones forgiven; WER ≥ 0.6 on lines of 4+ words; no WER rule on 1–2-word lines), duration ratio vs the Polish
   original outside 0.25–2.5×. Flagged lines get up to four more takes; whatever still fails plays from the installed pack.
   **Gender drift:** emotional takes (screams, pleading) can drift into the other gender even with a correct anchor;
   `gender_lines.py` classifies every installed line and `pick_gender_take.py <lines> man|woman` re-takes the mismatches.
   `audit_audio.py` scores every line (speaker similarity, pitch movement, pace, silences, clipping, cut-off endings).
5. **Install — `install_stage.py --lines <tsv> --skip-flagged`** → levels each line to -20 dB RMS (peaks ≤ -1 dBFS; NPC
   speech plays positionally, so quiet takes vanish at a distance) and writes 44.1 kHz mono 4-bit IMA ADPCM, the game's own
   speech format, into `<game>\_work\Data\Sound\Speech\` (inventory `work\installed.txt`; `--uninstall`).
   **Pack — `pack_mod.py`** → `Data\KM_SpeechJAN1.mod`, `KM_SpeechJAN2.mod`, … (VDFS, timestamp 2099-01-01, **each under
   1.5 GB**: the engine reads 32-bit signed offsets and entries past 2 GiB are silent) and registers them on the ini
   `[FILES] vdf=` line. **The game must be closed**: it reads archive offsets once at startup, so a repack under a running
   game breaks playback. `gamecheck.py` detects the game by working set, not handle count (the game's handle count reads 0).

### Unattended drivers (what produced the full game; all resumable, status in `work\<name>.status`)
- `svm_run.py` — all 74 stock-line sets: directions written once per distinct (token, text) and reused across sets,
  each set rendered in the voice of its main named speaker, QA, install, pack.
- `build_rest.py` then `run_rest.py` — all dialogue after chapter 1, block by block via `redo_lines.py --keep`
  (render, QA, one re-take, install, pack if the game is closed).
- `stage_extra_cast.py` then `run_extras.py` — voices for one-off NPCs the script never ties to a named character
  (gender and features from the Polish actor's audio), their lines plus every grunt and scream, and three more takes
  (seed offsets 2–4) for every line still failing QA.
- `redo_lines.py --lines <tsv> --directions …` — re-render any line set end to end (new directions or a new anchor).

## What mattered (blind rounds and measurements)
1. Every line directed (+0.9 over the original pack on identical voices). Model without direction lost to the pack.
2. Casting by description, not cloning: fits the character, no accidental accent, costs nothing in preference.
3. Pacing as a rule: unhurried by default; speed only when the character is plainly impatient.
4. Writer model didn't matter (Opus 5 = Sonnet 5 = Fable 5.1 = hand-written). Per-take variance did → QA + re-takes.
5. Breeze copies the anchor's melody: the anchor clip's pitch movement predicts every rendered line's (r = 0.86 over
   58 speakers), so a flat anchor makes a flat, "AI-sounding" character. Voice design also varies a lot by seed (same
   description: 4 vs 1 in a blind score), so recasting designs several seeds and picks.
6. Tempo: rendered words/sec jumps >1.5× between adjacent lines of one speaker in 24% of pairs even with identical pace
   directions (Breeze take variance). Picking the steadiest of K takes (`consistency_pick.py`) cut jumps from 8 to 3 of 48
   pairs on a demo, at K× the render time; the full run used single takes plus QA re-takes.
7. UTMOS is not a naturalness proxy here: the Polish human actors score 2.6, our lines 4.0.

## Revert
Delete `Data\KM_SpeechJAN*.mod` (or `python ours.py off`), remove them from `system\TheChroniclesOfMyrtana.ini`
(`vdf=` line), run `python install_stage.py --uninstall`. The `Gothic.ini` sound settings help any speech pack; keep them.

## License
The code is MIT (see `LICENSE`). The voice-over audio is an adaptation of *The Chronicles of Myrtana: Archolos*, released by its
team under the GothicMOD license (Archolos EULA, Annex B; German original of the relevant clauses in `GothicMOD_Lizenz_Auszug.txt`):
non-commercial, same license for adaptations, own title, and — as the license requires for altered works — the original authors are
credited as *basierend auf einem Werk von The Chronicles of Myrtana Team* rather than listed as authors of this version.
This is a fan project, not endorsed by the Archolos team.
