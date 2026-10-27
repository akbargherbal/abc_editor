#!/usr/bin/env python3
"""
review_tests.py - run the same fixed test cases against one or more versions of
abc_check.py and print a Markdown table of what each version actually does.

  python review_tests.py --script old=abc_check_old.py --script new=abc_check.py
  python review_tests.py --script old=... --script new=... --json results.json --raw raw_dir

No corpus needed: every case is generated from a small built-in score.
Python 3.8+, standard library only. Exit code is always 0 (read the table).

Verdicts: PASS / FAIL against the *correct* behaviour stated in each case,
INFO = no single correct behaviour, the observation is reported only.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

HEAD = "X:1\nT:\nM:2/4\nL:1/16\nQ:1/4=89\nV: Vocal clef=treble\nV: Ins clef=treble\nK:{key}\n"


def score(vocal, key="Gm", ins="Z4|\n", pre=""):
    return HEAD.format(key=key) + pre + "V: Vocal\n" + vocal + "V: Ins\n" + ins


BARS = ["G2G2A2B2", "B2B2A2G2", "D2D2F2F2", "G8", "A2A2B2B2", "c2c2B2A2", "G2G2F2F2", "G8"]
BASE_V = "|".join(BARS) + "|\n"


def variant(i, new_bar, pre=""):
    """BASE with bar i (0-based) replaced; `pre` is placed before it (e.g. an inline field or a K: line)."""
    b = list(BARS)
    b[i] = pre + new_bar
    return "|".join(b) + "|\n"
BASE = score(BASE_V)


def run(script, *args):
    p = subprocess.run([sys.executable, script, *args], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


def grab(pattern, text, default=""):
    m = re.search(pattern, text, re.M)
    return m.group(1).strip() if m else default


def vocal_block(out):
    m = re.search(r"^\[Vocal\].*?(?=^\[Ins\]|^SECTIONS|^RESULT|\Z)", out, re.S | re.M)
    return m.group(0) if m else out


def info_check(out):
    vb = vocal_block(out)
    return {
        "result": grab(r"^RESULT: (\w+)", out),
        "keysig": grab(r"key signature: (.*)\)\s*$", out),
        "classes": grab(r"pitch classes \(onsets\): (.*)$", vb),
        "ins_onsets": grab(r"^\[Ins\].*?onsets=(\d+)", out),
        "warnings": len(re.findall(r"^WARNING", out, re.M)),
    }


# ---------------------------------------------------------------- check cases
# (name, abc text, correct-behaviour description, predicate(info, exit, out) -> bool|None)
CHECK = [
    ("C1 inline [K:Fm] at bar start",
     score("G2G2A2B2|[K:Fm]G2G2A2B2|\n"),
     "VALID; later A->Ab, B->Bb (Ab present in pitch classes)",
     lambda i, e, o: i["result"] == "VALID" and "Ab" in i["classes"]),
    ("C2 body-level K: line",
     score("G2G2A2B2|\nK:Fm\nG2G2A2B2|\n"),
     "VALID; key applied (Ab present)",
     lambda i, e, o: i["result"] == "VALID" and "Ab" in i["classes"]),
    ("C3 K:D#m (D,F notes)",
     score("D2D2F2F2|\n", key="D#m"),
     "6 sharps; D->D#(Eb), F->F#; no 'not recognised' warning",
     lambda i, e, o: "F#" in i["classes"] and "Eb" in i["classes"] and "not recognised" not in o),
    ("C4 K:G#m (G,A notes)",
     score("G2G2A2A2|\n", key="G#m"),
     "5 sharps; G->G#(Ab), A->A#(Bb)",
     lambda i, e, o: "Ab" in i["classes"] and "Bb" in i["classes"]),
    ("C5 M: line while a bar is open",
     score("G2G2A2B2|G2G2\nM:1/4\nA2B2|G2G2|\n"),
     "no single correct behaviour (report only)",
     None),
    ("C6 inline [M:1/4] / [M:2/4] at bar start",
     score("G2G2A2B2|[M:1/4]G2G2|[M:2/4]G2A2B2c2|\n"),
     "VALID",
     lambda i, e, o: i["result"] == "VALID"),
    ("C7 inline [L:1/8] at bar start",
     score("G2G2A2B2|[L:1/8]G2A2|\n"),
     "VALID (bar 2 = 4 eighths = 2/4)",
     lambda i, e, o: i["result"] == "VALID"),
    ("C8a K:G Dorian",
     score("B2B2E2E2|\n", key="G Dorian"),
     "key signature = Bb only",
     lambda i, e, o: i["keysig"] == "Bb"),
    ("C8b K:A Minor",
     score("B2B2E2E2|\n", key="A Minor"),
     "key signature = none",
     lambda i, e, o: i["keysig"] == "none"),
    ("C8c K:G Mixolydian",
     score("B2B2E2E2|\n", key="G Mixolydian"),
     "key signature = none",
     lambda i, e, o: i["keysig"] == "none"),
    ("C8d K:Gdor (short form)",
     score("B2B2E2E2|\n", key="Gdor"),
     "key signature = Bb only",
     lambda i, e, o: i["keysig"] == "Bb"),
    ("C9 inline [V:Ins] voice switch",
     score("G2G2A2B2|[V:Ins]D2D2D2D2|\n"),
     "either exit != 0, or the 4 D notes end up in Ins (Ins onsets = 4)",
     lambda i, e, o: e != 0 or i["ins_onsets"] == "4"),
    ("C10 sanity: plain valid score",
     BASE,
     "VALID, exit 0",
     lambda i, e, o: i["result"] == "VALID" and e == 0),
]


def run_check_cases(script, tmp):
    rows = {}
    for name, text, _, pred in CHECK:
        f = os.path.join(tmp, "c.abc")
        open(f, "w", encoding="utf-8").write(text)
        code, out = run(script, "check", f)
        info = info_check(out)
        verdict = "INFO" if pred is None else ("PASS" if pred(info, code, out) else "FAIL")
        rows[name] = {"verdict": verdict, "exit": code, "info": info, "raw": out}
    return rows


# ---------------------------------------------------------------- diff cases
def vocal_line(out):
    return grab(r"^(\[Vocal\].*)$", out)


def changed_bars(out):
    return int(grab(r"changed bars: (\d+)", vocal_line(out), "-1"))


DIFF = [
    ("D1 insert [K:Fm] at start of a sounding bar",
     score(variant(2, "D2D2F2F2", "[K:Fm]")),
     "exit != 0 OR the edit is reported as a changed bar",
     lambda c, o: c != 0 or changed_bars(o) >= 1),
    ("D2 insert [M:2/4] at start of a sounding bar",
     score(variant(2, "D2D2F2F2", "[M:2/4]")),
     "exit != 0 OR reported as a changed bar",
     lambda c, o: c != 0 or changed_bars(o) >= 1),
    ("D3 insert body-level K:Fm line between bars",
     score(variant(2, "D2D2F2F2", "\nK:Fm\n")),
     "exit != 0 OR reported as a changed bar",
     lambda c, o: c != 0 or changed_bars(o) >= 1),
    ("D4 identical file",
     BASE,
     "exit 0, 0 changed bars",
     lambda c, o: c == 0 and changed_bars(o) == 0),
    ("D5 legit one-note edit (bar 3: D->E; 1 of 8 = 12.5%)",
     score(variant(2, "E2D2F2F2")),
     "exit 0, exactly 1 changed bar",
     lambda c, o: c == 0 and changed_bars(o) == 1),
    ("D6 bar of wrong length",
     score(variant(2, "D2D2F2F3")),
     "exit 1",
     lambda c, o: c == 1),
    ("D7 header K changed (Gm -> Fm)",
     score(BASE_V, key="Fm"),
     "exit 1",
     lambda c, o: c == 1),
    ("D8 non-target voice (Ins) changed",
     score(BASE_V, ins="G8|Z3|\n"),
     "exit 1",
     lambda c, o: c == 1),
    ("D9 budget exceeded (2 of 8 sounding bars, budget 15%)",
     score(variant(0, "G2G2A2c2").replace("D2D2F2F2", "E2E2F2F2")),
     "exit 2",
     lambda c, o: c == 2),
]


def run_diff_cases(script, tmp):
    base = os.path.join(tmp, "base.abc")
    open(base, "w", encoding="utf-8").write(BASE)
    rows = {}
    for name, text, _, pred in DIFF:
        f = os.path.join(tmp, "new.abc")
        open(f, "w", encoding="utf-8").write(text)
        code, out = run(script, "diff", base, f, "--budget", "0.15")
        rows[name] = {"verdict": "PASS" if pred(code, out) else "FAIL", "exit": code,
                      "info": {"vocal": vocal_line(out), "result": grab(r"^RESULT: (.*)$", out)}, "raw": out}
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", action="append", required=True, metavar="LABEL=PATH")
    ap.add_argument("--json")
    ap.add_argument("--raw", help="directory to save raw tool output per case")
    a = ap.parse_args()
    scripts = []
    for s in a.script:
        label, _, path = s.partition("=")
        if not path or not os.path.isfile(path):
            sys.exit(f"bad --script {s!r}")
        scripts.append((label, os.path.abspath(path)))
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        for label, path in scripts:
            results[label] = {"check": run_check_cases(path, tmp), "diff": run_diff_cases(path, tmp)}
    labels = [l for l, _ in scripts]
    print("| case | correct behaviour | " + " | ".join(labels) + " |")
    print("|---|---|" + "---|" * len(labels))
    for kind, cases in (("check", CHECK), ("diff", DIFF)):
        for c in cases:
            name, want = c[0], c[2]
            cells = []
            for l in labels:
                r = results[l][kind][name]
                if kind == "check":
                    i = r["info"]
                    obs = f"{r['verdict']} (exit {r['exit']}, {i['result'] or '?'}, key {i['keysig'] or '-'})"
                else:
                    obs = f"{r['verdict']} (exit {r['exit']}, {r['info']['result'] or '?'})"
                cells.append(obs)
            print(f"| {name} | {want} | " + " | ".join(cells) + " |")
    print()
    for l in labels:
        allr = list(results[l]["check"].values()) + list(results[l]["diff"].values())
        n = lambda v: sum(1 for r in allr if r["verdict"] == v)
        print(f"{l}: PASS={n('PASS')} FAIL={n('FAIL')} INFO={n('INFO')}")
    if a.json:
        slim = {l: {k: {n: {kk: vv for kk, vv in r.items() if kk != 'raw'} for n, r in d.items()}
                    for k, d in v.items()} for l, v in results.items()}
        json.dump(slim, open(a.json, "w"), indent=2, ensure_ascii=False)
    if a.raw:
        for l in labels:
            for kind in ("check", "diff"):
                for n, r in results[l][kind].items():
                    d = os.path.join(a.raw, l)
                    os.makedirs(d, exist_ok=True)
                    safe = re.sub(r"[^A-Za-z0-9]+", "_", n)[:60]
                    open(os.path.join(d, safe + ".txt"), "w", encoding="utf-8").write(r["raw"])


if __name__ == "__main__":
    main()
