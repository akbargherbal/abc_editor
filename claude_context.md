# claude_context.md: handoff for the next session

Written at the end of session 1 (date in session: 2026-10-27). **Read this fully before replying.** The user will start session 2 by giving you the AI agent's response (a `review_pack/`), and expects you to continue without re-explaining anything.

## 0. Quick start for session 2

1. Read this file. Do not re-derive things listed under "Established facts".
2. Ask the user to upload (files from session 1 are probably gone):
   - the agent's `review_pack/` (or at least `README.md`, `matrix.csv`, `02_summary.md`, `03_error_causes.md`, `05_changes.md`, `06_harness.md`, `06_notes.md`, `08_limits.md`),
   - the three scripts if needed: original `abc_check.py` (494 lines), the agent's modified `abc_check.py` (575 lines), and `review_tests.py`. Check their sha256 against section 5.
3. Your first task is **the review decision** in section 6 (accept / accept with changes / reject).
4. Follow the user's language (see section 9).

## 1. Project goal

The user has an AI-generated Arabic song (rated about **7/10**) made with the open-source lyrics-to-song model **m-a-p/YuE2-3B**. The goal is to reach about **9/10** by letting an LLM make **small, targeted edits to the song's melody ABC sheet**, then regenerating with the same prompt and lyrics.

Plan: an editor LLM receives `(style prompt, lyrics, melody ABC)`, first writes a **plan** (no revised ABC), waits for **approval**, then edits and verifies with a deterministic checker script. The user wants the system prompt to work with any mainstream medium/high-end LLM that has Python/shell access (they might use Claude for now).

## 2. Established facts

### 2.1 The user's files (session 1 uploads)
- `melody_score.abc` and `full_score.abc`: **same notes**, the full one adds automatic chord symbols (`Gm`, `Cm`, `F`, `Eb`). Differences otherwise only in rest notation (`z8` vs `Z`).
- `lyrics_prompt.json`: id `e1_ar_s03`, seed `1712905621`, options `cot: "off"`, `semantic_prefix_file: tokens/tokens_prefix_e1_3933.json`, semantic min/max tokens 3964, `export_semantic: true`. Style tags include `arabmaqamrock` (LoRA trigger word), "Maqam Hijaz", symphonic metal, powerful operatic, clear enunciation, mood "yearning, deep sorrow, lamenting".
- Lyrics: Ibn Zurayq al-Baghdadi's poem ("أستودع الله في بغداد لي قمراً…"), fully vowelized, meter **al-Basīṭ** (about 14 syllables per line). Sections: Intro, Verse 1, Chorus, Verse 2, Chorus, Outro; 24 lines, about **336 syllables** (rough rule: count short vowels + tanween).

### 2.2 ABC content (measured with my script)
- Header: `M:2/4 L:1/16 Q:1/4=89 K:Gm`. Voices **Vocal** and **Ins**, written as interleaved blocks. Inline `M:1/4` / `M:2/4` lines change meter. `Z<n>` = n bars of rest.
- **164 bars** per voice, about **3:38**. Sections by label: intro@1, verse@10, intro@22, verse@30, chorus@71, verse@85, interlude@134 (the ABC has 3 verse blocks; the lyrics have 2 verses + 2 choruses, so no 1:1 match).
- Vocal: 114 sounding bars, **430 note onsets** (ties merged), range D4..Bb5. Ins: 205 onsets, range C4..Eb6.
- **No accidentals**: natural G minor only. The prompt asks for Hijaz but the pitches contain no Hijaz intervals (Hijaz on G would use Ab and B natural).
- No `w:` lyric lines. 18 vocal phrases (split at rests of 1 bar or more) vs 24 lyric lines; 430 onsets vs about 336 syllables (ratio 1.28, likely melismas and transcription noise).
- Chord fit against the vocal melody: Gm 76%, F 67%, Cm 50%, Eb 33%, overall 66% (chance about 43%). Chords are weak; Cm and Eb are the weakest.

### 2.3 YuE2-3B (from web search, session 1; the model card text came via search snippets, I never saw the full API)
- Released by M-A-P around 2026-09-09/10, 3B parameters, AR-NAR Mixture-of-Transformers plus flow matching, CC BY-NC 4.0, about 24 GB VRAM.
- `cot` modes: `"full"` (plans melody + chords, default), `"melody"` (melody only), `"off"` (direct generation, no score).
- Official workflow: transcribe the existing song with **SheetSage2**, save its melody ABC **without chord symbols** as `melody.abc`, review or edit score and lyrics, then generate with `cot="melody"`, `abc=Path("melody.abc").read_text()`, a target style prompt and a seed. Agent-based editing is explicitly supported (turn feedback into score, style and lyric revisions).
- Reported benchmark results use **best-of-8 sampling**, so part of any 7→9 improvement may be seed luck.
- **Inference (unverified):** since the user's JSON has `cot: "off"` and the melody ABC has no chords, `melody_score.abc` is very likely a SheetSage2 transcription of the generated audio, and `full_score.abc` the version with chords. Not confirmed with the user.
- **Unknown:** exact `YuE2Pipeline` signature (lyrics/style argument names), what ABC dialect and constructs the model accepts, whether explicit accidentals (e.g. Hijaz) are honored.

### 2.4 Corrections I made during the session (do not repeat the old claims)
- I first doubted that ABC enters the model at all. **Wrong:** it is a first-class input.
- Hijaz does **not** need quarter tones (D: D Eb F# G A Bb C). The aug-2nd is the feature.
- I suggested `K:G exp _a _e` for Hijaz. **Unsafe**; use explicit per-note accidentals (`_A`, `=B`) and test.
- ABC cannot hold maqam ornamentation, microtones or free rhythm; it preserves structure (pitch, rhythm, chords), not feel.

## 3. What was built in session 1

| File | Purpose |
|---|---|
| `system_prompt.md` | Model-agnostic system prompt for the **ABC Score Refiner** (see 3.1) |
| `abc_check.py` (original) | Deterministic checker: `check`, `bars`, `fit`, `diff`. Python 3.8+, stdlib only |
| `review_request_for_agent.md` | Prompt the user forwards to their AI agent to get verifiable evidence (Tasks 1-8, `review_pack/`) |
| `review_tests.py` | Fixed harness (13 `check` cases + 9 `diff` cases) run against several script versions |
| `claude_context.md` | This file |

### 3.1 Design decisions in `system_prompt.md` (keep consistent)
- Two phases: **Phase 1 plan only** (no revised ABC, ends with an approval request), **Phase 2 execute** only after explicit approval; silence or questions are not approval.
- Inputs gate: needs STYLE_PROMPT, LYRICS, ABC; asks for optional listener notes.
- Edit budget: at most **15% of the sounding bars of the Vocal voice**; do not change headers, voice order, bar count or section order; do not touch `Ins` without approval; keep chord symbols byte-for-byte; no `w:`, tuplets, grace notes.
- Edit types in priority order: A artifact cleanup, B note-syllable fit, C phrase/cadence, D maqam pitch (**opt-in**, explicit accidentals), E rhythmic variety.
- Must verify with `abc_check.py` (exit 0 for `check` and `diff`); must not claim to hear audio; every finding has evidence and confidence; suggest regenerating with the same seed plus 2-3 others.

### 3.2 `abc_check.py` behavior (original)
- Bar numbering: 1-based per voice; `Z<n>` counts as n bars; interleaved blocks concatenated per voice; all-rest bars compare as `R` in diffs; chord symbols ignored.
- Exit codes: `0` ok, `1` hard error (invalid ABC, header/voice/bar-count change, non-target voice changed), `2` budget exceeded.
- It validated both user files as VALID, and its numbers match section 2.2.

## 4. The agent episode (why a review is pending)

The user ran `abc_check.py` through their AI agent on **177 transcribed scores**. The agent said it found errors, fixed them, and documented the fixes at the top of the script (a "Fixes" section in the module docstring). The user asked me to review.

### 4.1 What the agent changed (documented)
1. Inline bracketed fields `[K:..]`, `[M:..]`, `[L:..]` are parsed (before, `[K:Fm]` was read as music: phantom `F` note, unsupported-token errors).
2. Body-level `K:` lines change the key for the current voice (before: ignored with a warning).
3. `MAJOR_SHARPS` extended with `G# D# A# E# B#` and `Fb`, with double accidentals for signatures wider than 7 (before: `K:D#m` / `K:G#m` unrecognised).

### 4.2 My review findings (from tests I ran in session 1)
- The three documented fixes are **correct** (verified with hand-built cases; output on the user's two real files is byte-identical to the original).
- **Problem 1 (most serious):** `diff` is blind to inline `[K:..]` / `[M:..]` edits. Inline fields are not stored in the bar signature, so inserting `[K:Fm]` mid-score re-pitches later notes but `diff` reports 0 changed bars and exit 0. The original script blocked this (it errored on `[`). Separate nuance: a **body-level** `K:Fm` line was already invisible to `diff` in my original, and the agent's change does not close it.
- **Problem 2:** an **undocumented** behavior change: a body-level `M:` line arriving while a bar is open used to be a hard error (exit 1) and is now a warning with the meter change deferred. Defensible reading, but not in the docstring and it loosens validation.
- **Problem 3:** inline `[V:..]` is only warned about ("ignored/unsupported"); notes after it land in the wrong voice and the file stays VALID (exit 0).
- **Problem 4 (my bug, not the agent's):** mode names are case-sensitive and short-form only. `K:G Dorian` reads as F# (should be Bb), `K:A Minor` as 3 sharps (should be none), `K:G Mixolydian` as F# (should be none), silently. The agent's corpus pass presumably did not contain such keys.
- **Doc inaccuracy:** the docstring says `K:D#m` was "silently" misread; the original printed a "not recognised" warning.
- Cannot verify: the 177-file run itself, which files had which errors, and whether the agent modified any score.

### 4.3 Prototype fix I tested in a scratch copy (file lost; re-implement if needed)
- Mode parsing: regex `^\s*([A-G][#b]?)\s*([A-Za-z]*)`, lower-case the word, `mode = "m" if word == "m" else word[:3]`; unknown words fall back to major; add `ion: 0`, `aeo: -3` to `MODE_OFFSET`.
- `diff` visibility: store inline `[K:..]` / `[M:..]` (and body `K:`) in a per-voice `fields` list; the next bar created takes them as a **prefix of its signature and text** and clears the list. Result: edits show as changed bars and count against the budget. Harness: PASS=20 FAIL=1 INFO=1 (remaining FAIL: inline `[V:]`).
- Not yet done: making a newly introduced key/meter field a hard error in `diff`; making inline `[V:]` an error; updating the docstring.

## 5. Reference hashes and harness expectations

sha256:
- original `abc_check.py` (494 lines): `31a683221f413683a5c11b3ae6309f21204e77395c6f9c1320d53c6329dd6bb1`
- agent's `abc_check.py` (575 lines): `e06894436c1cc9d3d54754f532293a408fae0d6dd9b8f386626294b3d5f8b3fd`
- `review_tests.py` (252 lines): `962a4fb1b37fa8e3e69d20dc1070b98737e42968a372fcee3fba6af2dc408148`

Run: `python review_tests.py --script original=abc_check_original.py --script new=abc_check.py --json r.json --raw raw_dir`

**Expected results (use these to detect a tampered or mismatched run).** Original: PASS=11 FAIL=10 INFO=1. Agent version: PASS=14 FAIL=7 INFO=1.

| Case | original | agent |
|---|---|---|
| C1 inline `[K:Fm]`, C2 body `K:`, C3 `K:D#m`, C4 `K:G#m`, C6 inline `[M:]`, C7 inline `[L:]` | FAIL | PASS |
| C5 `M:` while bar open | INFO (exit 1) | INFO (exit 0) |
| C8a G Dorian, C8b A Minor, C8c G Mixolydian | FAIL | FAIL |
| C8d `Gdor`, C10 sanity | PASS | PASS |
| C9 inline `[V:Ins]` | PASS (exit 1) | FAIL (exit 0) |
| D1 inline `[K:]` in `diff`, D2 inline `[M:]` in `diff` | PASS (exit 1) | FAIL (exit 0, OK) |
| D3 body `K:` line in `diff` | FAIL | FAIL |
| D4-D9 | PASS | PASS |

## 6. Pending decision for session 2

The agent's reply (`review_pack/`) was requested via `review_request_for_agent.md` (Tasks 1-8). Judge it like this:

- **Accept:** no `.abc` file modified (or evidence is credible), no previously clean file (VALID, no warnings) changed output, original errors are checker limitations (valid ABC 2.1 constructs), harness numbers match section 5, FAIL rows explained honestly, all changes documented or admitted.
- **Accept with changes:** fixes hold up but recommend adopting the `diff` visibility and mode-name patches (section 4.3), documenting the `M:` change, correcting the "silently" wording, and handling `[V:]`.
- **Reject or investigate:** any sheet edited or unprovable, a clean file's output changed unexplained, harness numbers do not match, missing evidence, or claims contradicted by raw output.

Read first: `README.md`, `matrix.csv`, `02_summary.md`, `03_error_causes.md`, `05_changes.md`, `06_harness.md`, `06_notes.md`, `08_limits.md`. Check hashes in `manifest` and `scripts/`. Look especially at the census (`04_census.md`): counts of inline `[V:`, mid-bar `M:` lines and long/capitalized `K:` modes decide how much problems 2-4 matter for the user's data.

## 7. What to do after the review

1. Produce the **final `abc_check.py`** (agent's fixes plus the section 4.3 patches, plus docstring corrections) and re-run `review_tests.py`; deliver as a file with the harness table.
2. Update `system_prompt.md` only if needed (for example if the checker's commands or exit-code semantics change).
3. Help the user run the real loop on the song: baseline (seed `1712905621`) plus extra seeds; edit `melody_score.abc` only; generate with `cot="melody"`. Alternative path worth testing: `cot="full"`, then edit the model's own `score.abc`.
4. Open questions to ask the user: how were the ABC files produced (SheetSage2?); do they have the `YuE2Pipeline` call; which LLM will run the refiner; what sounded wrong in the 7/10 take (listener notes are the strongest signal).

## 8. Caveats the user should keep hearing

- The LLM cannot hear. ABC edits are hypotheses, judged by listening across several seeds.
- Maqam feel is mostly outside ABC; Hijaz-style edits are opt-in and may not be honored by the model.
- Unverified: how the ABC enters the generation exactly; everything about YuE2 comes from search snippets (model card text), not from running it.

## 9. User and working style

- Python developer; prefers **Markdown** for documentation. Writes in **Gulf Arabic dialect** (e.g. "شنو", "ليش") for most of the session, and in English in the last few turns. **Reply in the language of their latest message**, and keep code, ABC and technical terms in English.
- Wants honest, evidence-based review of the agent's work, not reassurance. Asks "exactly" questions and appreciates being corrected openly.
- Prefers deliverables as files; the finished prompt/scripts were delivered as files with brief chat summaries.
- Do not volunteer the user's city (Manama) unless location matters.

## 10. Environment notes (sandbox)

- `bash_tool` runs commands under `/bin/sh`: `${PIPESTATUS[0]}` fails there. Use `bash -c '...'` when needed.
- Files go to `/mnt/user-data/outputs`, then `present_files`. Uploaded files are read-only under `/mnt/user-data/uploads`.
- No skill applies to `.md`/`.py` deliverables here. Web search is available (and was required for YuE2 facts; re-check for newer YuE2 info if relevant, since things may have changed after 2026-10-27).
