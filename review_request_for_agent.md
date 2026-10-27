# Evidence request: your changes to `abc_check.py`

An independent reviewer will decide whether your work on `abc_check.py` is valid. The reviewer cannot see the 177-score corpus or your earlier session, so the decision depends entirely on the evidence you provide. Your job now is to **produce that evidence**, not to defend or extend your changes.

## Ground rules (read first)

1. **Read-only.** Do not modify, create, rename or delete any `.abc` file or any script in this pass. If you need a patched script for something, save it as a *new* file and say so.
2. **Raw output over summaries.** Every number or claim in your answer must point to a file in the pack that contains the raw output. Do not paraphrase tool output.
3. **Label every statement** as `[VERIFIED: <file or command>]` or `[ASSUMED]`. Do not mix them.
4. **Report negatives.** Files that still fail, warnings you suppressed, things you did not check, things you are unsure about, and anything that contradicts your earlier summary all go in the pack. Omitting a bad result is worse than reporting it.
5. **No new fixes.** Do not apply further changes to your version. Proposals go in a separate clearly named file (see Task 7).
6. If you cannot do a task, say exactly why instead of skipping it silently.

## Files you are working with

| File | What it is | sha256 |
|---|---|---|
| `abc_check_original.py` | The script **before** your changes (494 lines) | `31a683221f413683a5c11b3ae6309f21204e77395c6f9c1320d53c6329dd6bb1` |
| `abc_check.py` (yours) | The script **after** your changes (575 lines) | `e06894436c1cc9d3d54754f532293a408fae0d6dd9b8f386626294b3d5f8b3fd` |
| `review_tests.py` | Fixed test harness supplied by the reviewer | `962a4fb1b37fa8e3e69d20dc1070b98737e42968a372fcee3fba6af2dc408148` |
| the corpus | the 177 `.abc` scores | (you compute, Task 1) |

Verify these hashes first. If your copy of the original does not match, say so and stop at Task 1 with the hash you have. Do not reconstruct the original from memory.

## Task 1: Provenance

Produce `01_provenance.md` containing:

- Python version, OS, working directory, and the exact commands you ran during your earlier "corpus validation pass" (from your shell history or session log; if unavailable, say so).
- `sha256` of every corpus file (`manifest_corpus.sha256`), and of the scripts above.
- Answer **yes/no with evidence**: *Did you modify, create, delete or rename any `.abc` file at any time?* Evidence: version control history, a pre-run backup comparison, or file modification times. If you cannot prove it, write "cannot prove".
- Answer **yes/no**: *Did you change any script other than `abc_check.py`?*

## Task 2: Before/after matrix

Run the **original** and **your** version of `check` on every corpus file with the same invocation: `python SCRIPT check FILE`. Save raw outputs to `raw/original/<file>.txt` and `raw/new/<file>.txt` (include the exit code on the last line as `EXIT=<n>`).

Produce `matrix.csv` with one row per corpus file and these columns:

`file, orig_exit, orig_result, orig_problems, orig_warnings, new_exit, new_result, new_problems, new_warnings, output_changed (yes/no), pitch_classes_changed (yes/no), bars_changed (yes/no), key_changed (yes/no)`

Where `*_problems` is the number of `  - ` lines under RESULT and `*_warnings` the number of `WARNING:` lines. Then list in `02_summary.md`:

- counts of files by (orig_result → new_result),
- every file where **new is not VALID** (with the raw reason),
- every file where the original was **VALID with zero warnings** but the new output differs in any way (`output_changed = yes`). This is the most important list. If it is empty, say so.

## Task 3: What were the "errors"?

Produce `03_error_causes.md`. For every file that was INVALID or had warnings under the **original**, assign **exactly one primary cause** from this list (or `other: <describe>`):

`inline_K`, `inline_M`, `inline_L`, `body_K_line`, `sharp_key_unrecognised`, `mid_bar_M_line`, `other`

For each cause give: the count of files, the file names, and **one minimal ABC excerpt (≤3 lines)** copied verbatim from a real file. Also give a table of the original's raw message texts with counts (e.g. `unsupported token '[' ...: 412`).

Answer explicitly: *Were the errors defects in the scores, or limitations of the original checker?* with the evidence that supports your answer (e.g. are those constructs valid ABC 2.1?).

## Task 4: Census of constructs across the corpus

Produce `04_census.md` with counts **and file lists** (grep or script output pasted verbatim, with the command) for:

- inline `[V:`, `[K:`, `[M:`, `[L:`, and any other `[X:` inline field;
- body-level lines starting with `K:`, `M:`, `L:`, `Q:`, `V:`, `W:`, `w:`;
- **`M:` lines that arrive while a bar is still open**, i.e. the preceding music line of that voice does not end with a barline (this is the case behind your undocumented behaviour change, see Task 5);
- every distinct `K:` value with counts, flagging any that contain a capital letter in a mode name, a long mode name (Dorian, Minor, Mixolydian…), `exp`, `clef`, `HP`, `Hp`, or `none`;
- tuplets `(3`, chord brackets `[CEG]`, grace notes `{`, broken rhythm `>` `<`, `%%` directives, more than one tune per file (`X:` count > 1), voice names used.

## Task 5: Complete inventory of behavioural changes

Run `diff -u abc_check_original.py abc_check.py` and save it as `05_diff.patch`. In `05_changes.md`, list **every hunk** with: what it changes, which docstring "Fixes" bullet it belongs to, or `UNDOCUMENTED` if none does.

Specifically, the reviewer has observed that a body-level `M:` line arriving while a bar is open used to produce a hard error (original exit 1) and now produces only a warning (the meter change is deferred). Explain: why you made this change, whether it appears in the docstring, and how many corpus files' results depend on it (use Task 2 and Task 4 data).

Then, for **each docstring sentence under "Fixes"**, give a verdict: `Verified by <file/test>` or `Not verified`. In particular check the claim that `K:D#m` / `K:G#m` were *silently* misread: did the original print a warning for them? Quote the raw output.

## Task 6: Run the supplied test harness

```
python review_tests.py --script original=abc_check_original.py --script new=abc_check.py \
    --json 06_harness.json --raw 06_harness_raw > 06_harness.md
```

Do not edit `review_tests.py`. Include `06_harness.md`, the JSON and the raw directory. Then, in `06_notes.md`, **do not explain away FAIL rows**. For each FAIL in the `new` column, state in one or two sentences whether you believe the expectation in that row is wrong or the script is wrong, and why. The reviewer will judge.

Also run, and paste verbatim, the output of `check` on these two files (create them in a temp directory; do not add them to the corpus):

```
X:1
T:
M:2/4
L:1/16
Q:1/4=89
V: Vocal
K:G Dorian
V: Vocal
B2B2E2E2|
```
and the same with `K:A Minor`. Report the "key signature" line for each.

## Task 7: Proposals (optional, separate)

If you believe any change is warranted, put it in `abc_check_proposed.py` (a new file, never replacing yours) together with a `07_proposal.md` that says what each change fixes and re-runs `review_tests.py` with `--script proposed=abc_check_proposed.py` added. Include the same corpus matrix columns for the proposed version on any file whose result differs from `new`.

## Task 8: Limits of your own check

Produce `08_limits.md` listing: files you did not run or that crashed or timed out; any `try/except`, flag, threshold or exit-code semantics you changed; any warning you chose not to surface; and anything in your earlier summary ("found some errors and fixed them") that you can no longer support with the evidence above.

## Deliverable

One directory (and a `.zip` of it) named `review_pack/`:

```
review_pack/
  README.md                 # one page: answers to the 7 questions below, each citing files
  01_provenance.md  02_summary.md  03_error_causes.md  04_census.md
  05_changes.md  05_diff.patch  06_harness.md  06_harness.json  06_notes.md  08_limits.md
  matrix.csv  manifest_corpus.sha256
  raw/original/  raw/new/  06_harness_raw/
  scripts/ (original, yours, review_tests.py, and the proposed one if any)
```

If the corpus is small enough, include it as `corpus/`; otherwise include at least every file that appears in a list above.

`README.md` must answer, with `[VERIFIED: …]`/`[ASSUMED]` labels:

1. Did you modify any `.abc` file? (Task 1)
2. What exactly were the original errors, how many, and of which kinds? (Task 3)
3. Were they score defects or checker limitations? (Task 3)
4. Which corpus files depend on each documented fix? (Tasks 2–4)
5. Did any previously clean file (VALID, no warnings) change output? (Task 2)
6. What changed that you did not document? (Task 5)
7. What did you not verify? (Task 8)
