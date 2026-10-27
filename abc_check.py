#!/usr/bin/env python3
"""
abc_check.py - deterministic helper for refining melody ABC files.

Targets the dialect produced by audio-to-ABC transcribers (header X/T/M/L/Q/V/K,
voices interleaved in blocks, `Z<n>` multi-bar rests, inline `M:` changes,
chord symbols in quotes). Python 3.8+, standard library only.

Commands
  check FILE                      validate + summarize
  bars  FILE [--voice V] [--sounding]   numbered bars (the numbering convention)
  fit   FILE LYRICS [--voice V] [--gap 1/2]   phrases vs lyric lines (syllables)
  diff  OLD NEW [--voice V] [--budget 0.15]   what changed, validity, edit budget

Exit codes: 0 OK | 1 hard error (invalid ABC, header/bar-count change) | 2 budget exceeded

Bar numbering: 1-based, per voice. `Z<n>` counts as n bars. Interleaved voice
blocks are concatenated per voice. All-rest bars are compared as "R" in diffs
(so `Z` vs `z8` is not a change). Chord symbols are ignored.
"""
import argparse
import difflib
import json
import re
import signal
import sys
from collections import Counter
from fractions import Fraction as F

TOKEN = re.compile(r"""
  (?P<bar>\|\]|\|\||\|:|:\||::|\|)
 |(?P<note>(?P<acc>[\^_=]{1,2})?(?P<letter>[A-Ga-g])(?P<oct>[',]*)(?P<len>\d*/?\d*)(?P<tie>-)?)
 |(?P<rest>[zx])(?P<rlen>\d*/?\d*)
 |(?P<mrest>Z)(?P<mcount>\d*)
 |(?P<skip>[\s()])
 |(?P<other>.)
""", re.X)

BASE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MAJOR_SHARPS = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7,
                "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6, "Cb": -7}
MODE_OFFSET = {"": 0, "maj": 0, "lyd": 1, "mix": -1, "dor": -2, "m": -3, "min": -3, "phr": -4, "loc": -5}
SHARP_ORDER = "FCGDAEB"
FLAT_ORDER = "BEADGCF"


def plen(s):
    if not s:
        return F(1)
    if "/" not in s:
        return F(int(s))
    a, b = s.split("/", 1)
    return F(int(a) if a else 1, int(b) if b else 2)


def key_signature(k):
    """Return ({LETTER: offset}, recognised)."""
    m = re.match(r"^\s*([A-G][#b]?)\s*(maj|min|mix|dor|lyd|phr|loc|m)?", k)
    if not m or m.group(1) not in MAJOR_SHARPS:
        return {}, False
    n = MAJOR_SHARPS[m.group(1)] + MODE_OFFSET[m.group(2) or ""]
    sig = {}
    if n > 0:
        for L in SHARP_ORDER[:n]:
            sig[L] = 1
    elif n < 0:
        for L in FLAT_ORDER[:-n]:
            sig[L] = -1
    return sig, True


def pname(m):
    return NAMES[m % 12] + str(m // 12 - 1)


def parse_meter(s):
    s = s.strip()
    if s == "C":
        return F(4, 4)
    if s == "C|":
        return F(2, 2)
    a, b = s.split("/")
    return F(int(a), int(b))


class Voice:
    def __init__(self, name, meter, unit):
        self.name, self.meter, self.unit = name, meter, unit
        self.bars, self.cur = [], []
        self.acc = {}
        self.prev_tie = None


class Score:
    def __init__(self):
        self.header = {}
        self.voices = {}
        self.order = []
        self.sections = []
        self.errors = []
        self.warnings = []
        self.keysig, self.key_ok = {}, True
        self.tempo = (F(1, 4), 120)


def parse(path):
    sc = Score()
    in_header, cur, global_meter = True, None, None
    for ln, raw in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("%"):
            m = re.match(r"%\s*(\S+)", line)
            if m and not in_header and not line.startswith("%%"):
                sc.sections.append((m.group(1), {n: len(v.bars) for n, v in sc.voices.items()}))
            continue
        fm = re.match(r"^([A-Za-z]):\s*(.*)$", line)
        if in_header:
            if fm:
                f, val = fm.group(1), fm.group(2)
                if f == "V":
                    nm = val.split()[0] if val.split() else "1"
                    sc.header.setdefault("V", []).append(nm)
                else:
                    sc.header[f] = val
                if f == "K":
                    in_header = False
                    sc.keysig, sc.key_ok = key_signature(val)
                    if not sc.key_ok:
                        sc.warnings.append(f"K:{val} not recognised; pitch spelling may be off")
                    q = re.match(r"(\d+)/(\d+)=(\d+)", sc.header.get("Q", ""))
                    if q:
                        sc.tempo = (F(int(q.group(1)), int(q.group(2))), int(q.group(3)))
            continue
        # ---- body
        if fm and len(fm.group(1)) == 1 and fm.group(1) in "VMLKQWwP":
            f, val = fm.group(1), fm.group(2)
            if f == "V":
                if cur:
                    close_bar(sc, cur, unterminated=True)
                nm = val.split()[0] if val.split() else "1"
                cur = ensure_voice(sc, nm, global_meter)
            elif f == "M":
                try:
                    mt = parse_meter(val)
                except Exception:
                    sc.errors.append(f"line {ln}: bad M: {val}")
                    continue
                if cur is None:
                    global_meter = mt
                else:
                    if cur.cur:
                        close_bar(sc, cur, unterminated=True)
                    cur.meter = mt
            elif f == "L":
                try:
                    a, b = val.split("/")
                    if cur:
                        cur.unit = F(int(a), int(b))
                    else:
                        sc.header["L"] = val
                except Exception:
                    sc.errors.append(f"line {ln}: bad L: {val}")
            elif f in "WwKQP":
                sc.warnings.append(f"line {ln}: inline field {f}: ignored/unsupported")
            continue
        if cur is None:
            cur = ensure_voice(sc, "1", global_meter)
        text = re.sub(r"%.*$", "", line)
        text = re.sub(r'"[^"]*"', "", text)      # chord symbols
        text = re.sub(r"!\w+!", "", text)        # decorations
        for t in TOKEN.finditer(text):
            k = t.lastgroup
            if t.group("bar"):
                close_bar(sc, cur)
            elif t.group("note"):
                add_note(sc, cur, t)
            elif t.group("rest"):
                d = plen(t.group("rlen")) * cur.unit
                cur.cur.append({"k": "R", "dur": d, "text": t.group(0)})
            elif t.group("mrest"):
                if cur.cur:
                    sc.errors.append(f"line {ln}: multi-bar rest inside an open bar ({cur.name})")
                    close_bar(sc, cur, unterminated=True)
                for _ in range(int(t.group("mcount") or 1)):
                    cur.bars.append(make_bar(cur, [{"k": "R", "dur": cur.meter, "text": "Z"}], False))
            elif t.group("other"):
                sc.errors.append(f"line {ln}: unsupported token {t.group(0)!r} in voice {cur.name}")
    for v in sc.voices.values():
        close_bar(sc, v, unterminated=True)
    return sc


def ensure_voice(sc, name, global_meter):
    if name not in sc.voices:
        try:
            meter = global_meter or parse_meter(sc.header.get("M", "4/4"))
        except Exception:
            meter = F(4, 4)
        a, b = sc.header.get("L", "1/8").split("/")
        sc.voices[name] = Voice(name, meter, F(int(a), int(b)))
        sc.order.append(name)
    return sc.voices[name]


def add_note(sc, v, t):
    letter, octm, acc = t.group("letter"), t.group("oct"), t.group("acc")
    octave = (5 if letter.islower() else 4) + octm.count("'") - octm.count(",")
    key = (letter.upper(), octave)
    if acc:
        off = {"^": 1, "^^": 2, "_": -1, "__": -2, "=": 0}.get(acc, 0)
        v.acc[key] = off
    else:
        off = v.acc.get(key, sc.keysig.get(letter.upper(), 0))
    midi = 12 * (octave + 1) + BASE[letter.upper()] + off
    v.cur.append({"k": "N", "dur": plen(t.group("len")) * v.unit, "text": t.group(0),
                  "midi": midi, "tie": bool(t.group("tie")), "explicit_acc": bool(acc)})


def make_bar(v, events, unterminated):
    dur = sum((e["dur"] for e in events), F(0))
    notes = [e for e in events if e["k"] == "N"]
    sig = "R" if not notes else "".join(e["text"] for e in events)
    return {"meter": v.meter, "dur": dur, "events": events, "unterminated": unterminated,
            "ok": dur == v.meter, "sig": sig, "text": "".join(e["text"] for e in events)}


def close_bar(sc, v, unterminated=False):
    if not v.cur:
        return
    v.bars.append(make_bar(v, v.cur, unterminated))
    v.cur = []
    v.acc = {}


# ------------------------------------------------------------------ analysis
def onsets(v):
    """Yield (bar_no, event_start_in_whole_notes, event) for note onsets (ties merged)."""
    t, prev = F(0), None
    for i, b in enumerate(v.bars, 1):
        pos = F(0)
        for e in b["events"]:
            if e["k"] == "N":
                if not (prev is not None and prev == e["midi"]):
                    yield i, t + pos, e
                prev = e["midi"] if e["tie"] else None
            else:
                prev = None
            pos += e["dur"]
        t += b["dur"]


def phrases(v, gap):
    out, last_end, cur = [], None, None
    t = F(0)
    for i, b in enumerate(v.bars, 1):
        pos = F(0)
        for e in b["events"]:
            if e["k"] == "N":
                start = t + pos
                if cur is None or (last_end is not None and start - last_end >= gap):
                    cur = {"start": i, "end": i, "onsets": 0}
                    out.append(cur)
                cur["end"] = i
                last_end = start + e["dur"]
            pos += e["dur"]
        t += b["dur"]
    # onset counts per phrase
    for bar_no, _, _ in onsets(v):
        for p in out:
            if p["start"] <= bar_no <= p["end"]:
                p["onsets"] += 1
                break
    return out


def total_dur(v):
    return sum((b["dur"] for b in v.bars), F(0))


def seconds(sc, dur):
    beat, bpm = sc.tempo
    return float(dur / beat) * 60 / bpm


def mmss(s):
    return f"{int(s // 60)}:{int(s % 60):02d}"


def validity(sc):
    problems = list(sc.errors)
    for n in sc.order:
        v = sc.voices[n]
        for i, b in enumerate(v.bars, 1):
            if not b["ok"]:
                problems.append(f"{n} bar {i}: duration {b['dur']} != meter {b['meter']}  [{b['text']}]")
            if b["unterminated"]:
                problems.append(f"{n} bar {i}: bar not closed with a barline")
    return problems


# ------------------------------------------------------------------ commands
def cmd_check(a):
    sc = parse(a.file)
    h = sc.header
    print(f"FILE: {a.file}")
    print(f"HEADER: M:{h.get('M')} L:{h.get('L')} Q:{h.get('Q')} K:{h.get('K')}"
          f"  (key signature: {', '.join(f'{k}{"b" if o < 0 else "#"}' for k, o in sc.keysig.items()) or 'none'})")
    print(f"VOICES: {', '.join(sc.order)}")
    durs = {}
    for n in sc.order:
        v = sc.voices[n]
        ons = list(onsets(v))
        durs[n] = total_dur(v)
        pcs = Counter(NAMES[e['midi'] % 12] for _, _, e in ons)
        mids = [e["midi"] for _, _, e in ons]
        sounding = sum(1 for b in v.bars if any(e["k"] == "N" for e in b["events"]))
        explicit = sum(1 for _, _, e in ons if e["explicit_acc"])
        print(f"\n[{n}] bars={len(v.bars)} sounding_bars={sounding} onsets={len(ons)} "
              f"length={mmss(seconds(sc, durs[n]))} (at {h.get('Q')})")
        if mids:
            print(f"  range: {pname(min(mids))} .. {pname(max(mids))}")
            print("  pitch classes (onsets): " + ", ".join(f"{k} {c}" for k, c in pcs.most_common()))
            print(f"  explicit accidentals in body: {explicit}")
    if len(set(durs.values())) > 1:
        print("\nWARNING: voices have different total lengths: "
              + ", ".join(f"{n}={durs[n]}" for n in sc.order))
    if sc.sections:
        print("\nSECTIONS (bar index of Vocal-like first voice at label):")
        first = sc.order[0]
        print("  " + "  ".join(f"{lab}@{pos.get(first, 0) + 1}" for lab, pos in sc.sections))
    for w in sc.warnings:
        print("WARNING:", w)
    probs = validity(sc)
    print("\nRESULT:", "VALID" if not probs else f"INVALID ({len(probs)} problem(s))")
    for p in probs[:40]:
        print("  -", p)
    return 1 if probs else 0


def cmd_bars(a):
    sc = parse(a.file)
    v = sc.voices.get(a.voice)
    if not v:
        print(f"voice {a.voice!r} not found; have {sc.order}")
        return 1
    labels = {}
    for lab, pos in sc.sections:
        labels.setdefault(pos.get(a.voice, 0) + 1, []).append(lab)
    prev_meter = None
    for i, b in enumerate(v.bars, 1):
        for lab in labels.get(i, []):
            print(f"== {lab} ==")
        has = any(e["k"] == "N" for e in b["events"])
        if a.sounding and not has:
            continue
        m = f"{b['meter'].numerator}/{b['meter'].denominator}"
        flag = "" if b["ok"] else "  <-- BAD LENGTH"
        mark = "*" if m != prev_meter and prev_meter is not None else " "
        prev_meter = m
        print(f"{i:4d}{mark}{m:>4}  {b['text']}{flag}")
    return 0


def load_lyrics(path):
    raw = open(path, encoding="utf-8").read()
    if path.lower().endswith(".json"):
        d = json.loads(raw)
        raw = d["lyrics"] if isinstance(d, dict) and "lyrics" in d else raw
    out, cur = [], "(none)"
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("///"):
            continue
        m = re.match(r"^\[([^\]|]+)", s)
        if m:
            cur = m.group(1).strip()
            continue
        out.append((cur, s))
    return out


def syllables(line):
    """Rough count. Arabic (vowelized): short vowels + tanween. Else Latin vowel groups.
    Approximate (+-1-2/line): ignores elision (wasl) and unmarked vowels."""
    line = re.sub(r"[()]", "", line)
    ar = sum(line.count(c) for c in "\u064E\u064F\u0650\u064B\u064C\u064D")
    if ar:
        return ar
    return len(re.findall(r"[aeiouyAEIOUY]+", line))


def cmd_fit(a):
    sc = parse(a.file)
    v = sc.voices.get(a.voice)
    if not v:
        print(f"voice {a.voice!r} not found; have {sc.order}")
        return 1
    gap = F(a.gap)
    ph = phrases(v, gap)
    ly = load_lyrics(a.lyrics)
    print(f"VOCAL PHRASES (split at rests >= {gap} whole note): {len(ph)}")
    for i, p in enumerate(ph, 1):
        print(f"  P{i:02d} bars {p['start']:>3}-{p['end']:<3} onsets={p['onsets']}")
    print(f"\nLYRIC LINES: {len(ly)}")
    for i, (sec, s) in enumerate(ly, 1):
        print(f"  L{i:02d} [{sec}] syl~{syllables(s)}  {s}")
    so, ss = sum(p["onsets"] for p in ph), sum(syllables(s) for _, s in ly)
    print(f"\nTOTALS: onsets={so} syllables~{ss} ratio={so / ss:.2f}" if ss else "\nTOTALS: no syllables found")
    print("NOTE: phrase<->line alignment is NOT established by this tool. Syllable counts are approximate.")
    return 0


def vsigs(v):
    return [b["sig"] for b in v.bars]


def note_tokens(bars):
    return [e["text"] for b in bars for e in b["events"] if e["k"] == "N"]


def cmd_diff(a):
    old, new = parse(a.old), parse(a.new)
    hard = []
    for f in "MLQK":
        if old.header.get(f) != new.header.get(f):
            hard.append(f"header {f}: {old.header.get(f)!r} -> {new.header.get(f)!r}")
    if old.order != new.order:
        hard.append(f"voice list changed: {old.order} -> {new.order}")
    for p in validity(new):
        hard.append("new file: " + p)
    target_changed_bars, target_sounding = 0, 1
    for n in old.order:
        if n not in new.voices:
            continue
        ov, nv = old.voices[n], new.voices[n]
        os_, ns_ = vsigs(ov), vsigs(nv)
        if len(os_) != len(ns_):
            hard.append(f"{n}: bar count {len(os_)} -> {len(ns_)}")
        sm = difflib.SequenceMatcher(None, os_, ns_, autojunk=False)
        changed, notes_changed, blocks = 0, 0, []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            changed += max(i2 - i1, j2 - j1)
            ot, nt = note_tokens(ov.bars[i1:i2]), note_tokens(nv.bars[j1:j2])
            s2 = difflib.SequenceMatcher(None, ot, nt, autojunk=False)
            notes_changed += sum(max(x2 - x1, y2 - y1) for t2, x1, x2, y1, y2 in s2.get_opcodes() if t2 != "equal")
            blocks.append((tag, i1 + 1, i2, j1 + 1, j2,
                           " | ".join(b["text"] for b in ov.bars[i1:i2]),
                           " | ".join(b["text"] for b in nv.bars[j1:j2])))
        sounding = sum(1 for b in ov.bars if b["sig"] != "R") or 1
        print(f"[{n}] bars {len(os_)} -> {len(ns_)} | changed bars: {changed} "
              f"({changed / sounding:.1%} of {sounding} sounding bars) | notes touched: {notes_changed}")
        for tag, a1, a2, b1, b2, ot, nt in blocks:
            print(f"   {tag:8} old {a1}-{a2}  new {b1}-{b2}")
            print(f"      - {ot}")
            print(f"      + {nt}")
        if n == a.voice:
            target_changed_bars, target_sounding = changed, sounding
        elif changed:
            hard.append(f"voice {n} changed but is not the target voice ({a.voice})")
    print()
    for h in hard:
        print("ERROR:", h)
    frac = target_changed_bars / target_sounding
    over = frac > a.budget
    print(f"BUDGET: {frac:.1%} of sounding {a.voice} bars changed (limit {a.budget:.0%}) -> "
          + ("EXCEEDED" if over else "ok"))
    print("RESULT:", "HARD ERRORS" if hard else ("OVER BUDGET" if over else "OK"))
    return 1 if hard else (2 if over else 0)


def main():
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    c = s.add_parser("check"); c.add_argument("file"); c.set_defaults(fn=cmd_check)
    b = s.add_parser("bars"); b.add_argument("file"); b.add_argument("--voice", default="Vocal")
    b.add_argument("--sounding", action="store_true"); b.set_defaults(fn=cmd_bars)
    f = s.add_parser("fit"); f.add_argument("file"); f.add_argument("lyrics")
    f.add_argument("--voice", default="Vocal"); f.add_argument("--gap", default="1/2"); f.set_defaults(fn=cmd_fit)
    d = s.add_parser("diff"); d.add_argument("old"); d.add_argument("new")
    d.add_argument("--voice", default="Vocal"); d.add_argument("--budget", type=float, default=0.15)
    d.set_defaults(fn=cmd_diff)
    a = p.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
