#!/usr/bin/env python3
"""Front Row helper: find exam-hint candidates in a lecture transcript, check hints against the course
materials, keep each class's running list, and render the one-page pre-exam PDF.

Cubbie fetches everything (the transcript, Canvas files, dates) and passes it in. This script never calls Canvas
or the network. Saved hints live under ~/.config/front-row (or $SKILL_DATA_DIR), one JSON file per class, which
survives sandbox restarts and Skill updates.

Commands:
  scan   --transcript FILE                      candidate hint moments, ranked, with minutes in
  match  --hints FILE --materials DIR [--out F] check each hint against slide and page text
  save   --course C --date YYYY-MM-DD --hints FILE
  list   --course C [--short] [--json]           the running list (--short: night-before list)
  pdf    --course C --exam NAME --out FILE [--checks FILE]
  call   --course C --exam NAME [--time "10 AM"] what to say on the exam-morning wake-up call
  export --course C --out FILE.md [--date D] [--transcript FILE] [--exam NAME]
                                                 Markdown notes to save or paste into any AI model
  courses                                        classes with saved hints

Every command takes --sample, which uses the bundled files under assets/ and leaves saved hints alone.

Exit codes: 0 ok, 2 bad arguments or unreadable input, 3 nothing saved for that class, 4 a package is missing
(run Setup in SKILL.md).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SAMPLE_TRANSCRIPT = ASSETS / "sample_transcript.txt"
SAMPLE_HINTS = ASSETS / "sample_hints.json"
SAMPLE_MATERIALS = ASSETS / "sample_materials"

RANKS = ("direct", "strong", "repeated", "skip")
RANK_ORDER = {rank: i for i, rank in enumerate(RANKS)}
LABEL = {"direct": "DIRECT", "strong": "STRONG", "repeated": "REPEATED", "skip": "NOT ON EXAM"}
STATUSES = ("slides", "only_lecture", "not_checked")
WORDS_PER_MINUTE = 130  # typical lecture pace, used when the transcript has no timestamps
OUTPUT_CHARS = 7500  # Cubbie reads the first 8,000 characters of a command's output
FOUND, UNCLEAR = 80, 55  # match scores: at or above FOUND is in the slides, below UNCLEAR is not

EXAM = r"(?:exam|test|midterm|final|quiz)"
SKIP_PATTERNS = [
    rf"\b(?:won'?t|will not|isn'?t|is not|not gonna|not going to)\s+(?:be\s+)?on\s+(?:the|your)\s+{EXAM}",
    r"\byou\s+(?:don'?t|do not)\s+(?:need|have)\s+to\s+(?:know|memorize|worry about)\b",
    r"\b(?:not|won'?t be)\s+(?:responsible|tested)\b",
    rf"\bnot\s+(?:something|a thing)\s+(?:i'?ll|i will)\s+(?:test|ask)\b",
]
DIRECT_PATTERNS = [
    rf"\b(?:will|is going to|gonna|'ll)\s+(?:definitely\s+|probably\s+|absolutely\s+)?(?:be|show up|appear)\s+on\s+(?:the|your)\s+{EXAM}",
    rf"\bon\s+(?:the|your)\s+{EXAM}\b",
    rf"\b{EXAM}\s+question\b",
    r"\byou\s+(?:need|have|want|got)\s+to\s+know\s+(?:this|that|these|how)\b",
    r"\bi'?d\s+(?:study|know|review|memorize)\s+(?:this|that|these)\b",
    r"\b(?:shows?|comes?)\s+up\s+every\s+(?:year|semester|time|exam)\b",
    r"\b(?:i\s+)?guarantee\b",
    r"\byou'?ll\s+see\s+this\s+again\b",
]
STRONG_PATTERNS = [
    r"\b(?:this|that|it)\s+is\s+(?:really\s+|super\s+|very\s+)?important\b",
    r"\b(?:this|that)'s\s+(?:really\s+|super\s+|very\s+)?important\b",
    r"\bremember\s+(?:this|that)\b",
    r"\bwrite\s+(?:this|that)\s+down\b",
    r"\bif\s+you\s+remember\s+one\s+thing\b",
    r"\b(?:people|students|everyone|you\s+guys)\s+always\s+(?:get|mess|mix|confuse)\b",
    r"\bcommon\s+mistake\b",
    r"\bthis\s+(?:type|kind)\s+of\s+(?:problem|question)\b",
    r"\bpay\s+attention\b",
    r"\bkey\s+(?:concept|point|idea|takeaway)\b",
    r"\bmake\s+sure\s+you\s+(?:understand|know|can)\b",
]
COMPILED = {
    "skip": [re.compile(p, re.I) for p in SKIP_PATTERNS],
    "direct": [re.compile(p, re.I) for p in DIRECT_PATTERNS],
    "strong": [re.compile(p, re.I) for p in STRONG_PATTERNS],
}
TIMESTAMP = re.compile(r"^\s*\[?(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\]?\s*")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
STOPWORDS = set("""
a about above after again all also am an and any are as at be because been before being below between both but by
can could did do does doing down during each few for from further had has have having he her here hers him his how
i if in into is it its itself just let like me more most my no nor not now of off ok okay on once only or other our
out over own really right same she should so some such than that thats the their them then there these they this
those through to too under until up very was we were what when where which while who whom why will with would yeah
you your yours um uh gonna wanna gotta kind sort thing things going get got one two see say said know think mean
actually basically guys today look go well want need make way lot little bit time okay alright here's it's that's
we're you're they're don't can't won't i'm i'll you'll we'll let's
""".split())


def fail(message: str, code: int = 2):
    print(message, file=sys.stderr)
    sys.exit(code)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        fail(f"Can't read {path}: {exc.strerror}")


def read_json(path: Path):
    try:
        return json.loads(read_text(path))
    except ValueError as exc:
        fail(f"{path} isn't valid JSON: {exc}")


def emit(text: str) -> None:
    if len(text) > OUTPUT_CHARS:
        text = text[:OUTPUT_CHARS].rsplit("\n", 1)[0] + "\n... (cut; rerun with --json --out FILE for everything)"
    print(text)


# ---------------------------------------------------------------- scan


def sentences(transcript: str):
    """Yield (minute, sentence, stamped, words before it). Minutes come from [mm:ss] stamps when present, else
    from speaking pace."""
    words_so_far, stamped = 0, None
    for line in transcript.splitlines():
        stamp = TIMESTAMP.match(line)
        if stamp:
            hours, minutes, _ = stamp.groups()
            stamped = int(hours or 0) * 60 + int(minutes)
            line = line[stamp.end():]
        for sentence in SENTENCE.split(line.strip()):
            if not sentence:
                continue
            minute = stamped if stamped is not None else words_so_far // WORDS_PER_MINUTE
            yield minute, sentence.strip(), stamped is not None, words_so_far
            words_so_far += len(sentence.split())


def classify(sentence: str) -> tuple[str, str, int] | None:
    """(rank, the words that matched, where they start) for the first hint phrase in a sentence."""
    for rank in ("skip", "direct", "strong"):
        for pattern in COMPILED[rank]:
            found = pattern.search(sentence)
            if found:
                return rank, found.group(0), found.start()
    return None


def content_words(text: str) -> list[str]:
    """Meaningful words and numbers; numbers count because "30 to 32" is exactly what slides tend to leave out."""
    words = re.findall(r"[a-z0-9][a-z0-9'+-]*", text.lower())
    return [w for w in words if w not in STOPWORDS and (len(w) > 2 or w.isdigit())]


def repeated_concepts(transcript: str, minimum: int = 3, top: int = 8) -> list[dict]:
    """Two-word phrases the professor keeps coming back to, a hint the concept matters."""
    counts, first_minute = Counter(), {}
    for minute, sentence, _, _ in sentences(transcript):
        words = content_words(sentence)
        for pair in {f"{a} {b}" for a, b in zip(words, words[1:]) if a != b}:
            counts[pair] += 1
            first_minute.setdefault(pair, minute)
    picked = []
    for phrase, count in counts.most_common():
        if count < minimum or len(picked) >= top:
            break
        if any(set(phrase.split()) & set(p["phrase"].split()) for p in picked):
            continue  # "krebs cycle" and "cycle products" are the same concept
        picked.append({"phrase": phrase, "count": count, "first_minute": first_minute[phrase]})
    return picked


def scan(transcript: str) -> dict:
    found, previous, timed = [], "", False
    for minute, sentence, stamped, before in sentences(transcript):
        timed = timed or stamped
        hit = classify(sentence)
        if hit:
            rank, cue, start = hit
            if not stamped:  # unpunctuated transcripts make long "sentences"; place the cue itself
                minute = (before + len(sentence[:start].split())) // WORDS_PER_MINUTE
            context = f"{previous} {sentence}".strip() if len(sentence) < 80 else sentence[max(0, start - 160):start + 80]
            found.append({"rank": rank, "minute": minute, "cue": cue, "context": context[-240:]})
        previous = sentence
    found.sort(key=lambda h: (RANK_ORDER[h["rank"]], h["minute"]))
    words = len(transcript.split())
    return {
        "words": words,
        "minutes": words // WORDS_PER_MINUTE if not timed else None,
        "timestamps": "from transcript" if timed else f"estimated at {WORDS_PER_MINUTE} words a minute",
        "candidates": found,
        "repeated": repeated_concepts(transcript),
    }


def format_scan(result: dict) -> str:
    approx = "" if result["timestamps"] == "from transcript" else "~"
    lines = [f"{len(result['candidates'])} candidate moments in {result['words']} words "
             f"(minutes {result['timestamps']}). Candidates only: read each one and decide.", ""]
    for c in result["candidates"]:
        lines.append(f"[{LABEL[c['rank']]}] min {approx}{c['minute']}: \"{c['cue']}\"")
        lines.append(f"    {c['context']}")
    if result["repeated"]:
        lines += ["", "Came back to 3+ times:"]
        lines += [f"  {r['phrase']} x{r['count']} (first at min {approx}{r['first_minute']})" for r in result["repeated"]]
    if not result["candidates"] and not result["repeated"]:
        lines.append("No hint phrases found. Read the transcript yourself before telling the student there are none.")
    return "\n".join(lines)


# ---------------------------------------------------------------- match


def pdf_pages(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader  # installed in the Skill's venv (SKILL.md, Setup)
    except ImportError:
        raise RuntimeError("pypdf is not installed (run Setup)")
    return [page.extract_text() or "" for page in PdfReader(str(path)).pages]


def material_units(folder: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """Every readable page as (label, text), and the files that couldn't be read."""
    units, unreadable = [], []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        name, suffix = path.relative_to(folder).as_posix(), path.suffix.lower()
        try:
            if suffix == ".pdf":
                pages = pdf_pages(path)
                units += [(f"{name} p.{i}", text) for i, text in enumerate(pages, 1) if text.strip()]
                if not any(text.strip() for text in pages):
                    unreadable.append(f"{name} (no text layer)")
            elif suffix in {".html", ".htm"}:
                units.append((name, html.unescape(re.sub(r"<[^>]+>", " ", path.read_text(errors="replace")))))
            elif suffix in {".txt", ".md", ".csv", ".json"}:
                units.append((name, path.read_text(errors="replace")))
            else:
                unreadable.append(f"{name} (unsupported type)")
        except Exception as exc:  # a broken file shouldn't stop the others
            unreadable.append(f"{name} ({exc})")
    return units, unreadable


def stem(word: str) -> str:
    return word[:5] if len(word) > 5 else word.rstrip("s")


def score(concept: str, text: str) -> int:
    """0-100: the share of a concept's words that one page contains. With rapidfuzz installed, a near spelling
    counts too (transcripts mangle terms: "krebbs", "glycolisis")."""
    wanted = {stem(w) for w in content_words(concept)}
    if not wanted:
        return 0
    have = {stem(w) for w in content_words(text)}
    hits = wanted & have
    try:
        from rapidfuzz import fuzz, process  # optional; installed in the Skill's venv (SKILL.md, Setup)
    except ImportError:
        pass
    else:
        for word in wanted - hits:
            if not word.isdigit() and len(word) > 3 and process.extractOne(word, have, scorer=fuzz.ratio, score_cutoff=80):
                hits.add(word)
    return round(100 * len(hits) / len(wanted))


def match(hints: list[dict], folder: Path) -> dict:
    units, unreadable = material_units(folder)
    checked = []
    for hint in hints:
        hint = dict(hint)
        if hint.get("rank") == "skip":
            checked.append(hint)
            continue
        best = max(((score(hint["concept"], text), label) for label, text in units), default=(0, None))
        hint["match_score"], hint["material"] = best[0], best[1] if best[0] >= UNCLEAR else None
        if best[0] >= FOUND:
            hint["status"] = "slides"
        elif best[0] < UNCLEAR and units and not unreadable:
            hint["status"] = "only_lecture"
        else:
            hint["status"] = "not_checked"
        checked.append(hint)
    rated = [h for h in checked if h.get("rank") != "skip"]
    unclear = sum(1 for h in rated if h["status"] == "not_checked")
    dropped = bool(rated) and unclear * 3 > len(rated)
    if dropped:  # too unsure to trust any only-in-lecture flag from this lecture
        for h in rated:
            if h["status"] == "only_lecture":
                h["status"] = "not_checked"
    files = sorted({label.split(" p.")[0] for label, _ in units})
    return {"hints": checked, "searched": files, "unreadable": unreadable, "only_lecture_dropped": dropped}


def format_match(result: dict) -> str:
    lines = [f"Searched {len(result['searched'])} file(s): {', '.join(result['searched']) or 'none'}"]
    if result["unreadable"]:
        lines.append(f"Couldn't read: {', '.join(result['unreadable'])}")
    if result["only_lecture_dropped"]:
        lines.append("Over a third of the hints were unclear, so this lecture gets no only-in-lecture flags. "
                     "Tell the student in one line.")
    lines.append("")
    for h in result["hints"]:
        if h.get("rank") == "skip":
            lines.append(f"[NOT ON EXAM] {h['concept']}")
            continue
        where = f" -> {h['material']}" if h.get("material") else ""
        lines.append(f"[{h['status']}] {h['concept']} (score {h['match_score']}){where}")
    return "\n".join(lines)


# ---------------------------------------------------------------- store


def data_dir() -> Path:
    return Path(os.environ.get("SKILL_DATA_DIR") or Path.home() / ".config" / "front-row")


def course_file(course: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", course.lower()).strip("-")
    if not slug:
        fail("Give the class a name, for example --course \"BIO 181\".")
    return data_dir() / f"{slug}.json"


def load_course(course: str) -> dict:
    path = course_file(course)
    if not path.exists():
        return {"course": course, "hints": []}
    return read_json(path)


def save_course(store: dict) -> None:
    path = course_file(store["course"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(store, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)  # never leave a half-written list behind


def clean_hint(hint: dict, date: str) -> dict:
    if not isinstance(hint, dict) or not str(hint.get("concept", "")).strip():
        fail(f"Every hint needs a concept: {json.dumps(hint)[:120]}")
    rank = hint.get("rank", "strong")
    if rank not in RANKS:
        fail(f"Rank must be one of {', '.join(RANKS)}, not {rank!r}.")
    status = hint.get("status", "not_checked")
    if status not in STATUSES:
        fail(f"Status must be one of {', '.join(STATUSES)}, not {status!r}.")
    keep = {k: hint[k] for k in ("minute", "quote", "link", "material") if hint.get(k) not in (None, "")}
    return {"concept": hint["concept"].strip(), "rank": rank, "status": status, "date": date, **keep}


def add_hints(store: dict, hints: list[dict], date: str) -> tuple[int, int]:
    added = replaced = 0
    for hint in (clean_hint(h, date) for h in hints):
        key = (hint["concept"].casefold(), date)
        for i, old in enumerate(store["hints"]):
            if (old["concept"].casefold(), old["date"]) == key:
                store["hints"][i], replaced = hint, replaced + 1
                break
        else:
            store["hints"].append(hint)
            added += 1
    return added, replaced


def grouped(store: dict) -> list[dict]:
    """One entry per concept across lectures: its best rank, every date, and the strongest status evidence."""
    by_concept: dict[str, dict] = {}
    for h in store["hints"]:
        g = by_concept.setdefault(h["concept"].casefold(), {**h, "dates": [], "quotes": []})
        g["dates"].append(h["date"])
        if h.get("quote"):
            g["quotes"].append(h["quote"])
        if RANK_ORDER[h["rank"]] < RANK_ORDER[g["rank"]]:
            g["rank"] = h["rank"]
        if h["status"] == "slides" or g["status"] == "not_checked":
            g["status"], g["link"], g["material"] = h["status"], h.get("link"), h.get("material")
    out = list(by_concept.values())
    out.sort(key=lambda g: (RANK_ORDER[g["rank"]], -len(g["dates"]), g["concept"].lower()))
    return out


def where(g: dict) -> str:
    if g["status"] == "slides":
        return g.get("link") or g.get("material") or "in the slides"
    return "Only said in lecture" if g["status"] == "only_lecture" else "not checked against the slides"


def format_list(store: dict, short: bool) -> str:
    groups = grouped(store)
    keep = [g for g in groups if g["rank"] != "skip" and (not short or g["rank"] == "direct" or g["status"] == "only_lecture")]
    skips = [g for g in groups if g["rank"] == "skip"]
    lectures = len({h["date"] for h in store["hints"]})
    direct = sum(1 for g in groups if g["rank"] == "direct")
    lines = [f"{store['course']}: {len(keep)} hints from {lectures} lecture(s), {direct} direct"]
    for g in keep:
        said = f" \"{g['quotes'][0]}\"" if g["quotes"] else ""
        times = f", said in {len(g['dates'])} lectures" if len(g["dates"]) > 1 else ""
        lines.append(f"[{LABEL[g['rank']]}] {g['concept']}{said} ({', '.join(sorted(set(g['dates'])))}{times}) - {where(g)}")
    if skips and not short:
        lines += ["", "Said NOT on the exam:"] + [f"  {g['concept']}" for g in skips]
    return "\n".join(lines)


# ---------------------------------------------------------------- pdf


def render_pdf(store: dict, exam: str, out: Path, checks: dict) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Frame, KeepInFrame, Paragraph, Spacer
        from reportlab.pdfgen.canvas import Canvas
    except ImportError:
        fail("reportlab is not installed (run Setup), or make the PDF with Cubbie's documents ability.", 4)

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=12, spaceAfter=3)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.HexColor("#555555"))
    head = ParagraphStyle("head", parent=styles["Heading3"], spaceBefore=8, spaceAfter=3)
    tint = {"direct": "#C2410C", "strong": "#B45309", "repeated": "#1D4ED8", "skip": "#6B7280"}
    e = html.escape

    groups = grouped(store)
    lectures = len({h["date"] for h in store["hints"]})
    story = [Paragraph(e(f"Front Row: {store['course']} {exam}"), styles["Title"]),
             Paragraph(e(f"{sum(1 for g in groups if g['rank'] != 'skip')} hints from {lectures} "
                         f"lecture{'s' if lectures != 1 else ''}. What your professor said, "
                         "not a promise of what's on the exam."), small)]
    for rank in ("direct", "strong", "repeated"):
        items = [g for g in groups if g["rank"] == rank]
        if not items:
            continue
        story.append(Paragraph(f'<font color="{tint[rank]}">{LABEL[rank]}</font>', head))
        for g in items:
            said = f': <i>"{e(g["quotes"][0])}"</i>' if g["quotes"] else ""
            spot = where(g)
            spot = f'<link href="{e(spot)}" color="blue">Canvas</link>' if spot.startswith("https://") else e(spot)
            story.append(Paragraph(f"<b>{e(g['concept'])}</b>{said}", body))
            story.append(Paragraph(f"{e(', '.join(sorted(set(g['dates']))))} &middot; {spot}", small))
            question = checks.get(g["concept"]) or checks.get(g["concept"].casefold())
            if question and rank == "direct":
                story.append(Paragraph(f"Self-check: {e(question)}", small))
    skips = [g for g in groups if g["rank"] == "skip"]
    if skips:
        story.append(Paragraph(f'<font color="{tint["skip"]}">Said NOT on the exam</font>', head))
        story.append(Paragraph(e(", ".join(g["concept"] for g in skips)), body))
    story.append(Spacer(1, 6))

    width, height = letter
    canvas = Canvas(str(out), pagesize=letter)
    canvas.setTitle(f"Front Row: {store['course']} {exam}")
    frame = Frame(0.6 * inch, 0.6 * inch, width - 1.2 * inch, height - 1.2 * inch, showBoundary=0)
    frame.addFromList([KeepInFrame(frame._aW, frame._aH, story, mode="shrink")], canvas)  # always one page
    canvas.save()


# ---------------------------------------------------------------- call


def speakable(text: str) -> str:
    """Read-aloud form: no links or symbols a voice would trip on ("O(n)" becomes "O of n")."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\bO\(([^)]*)\)", r"O of \1", text)
    text = text.replace("+", " plus ").replace("&", " and ").replace("/", " or ")
    return re.sub(r"\s+", " ", re.sub(r"[()\[\]{}*_#`\"]", "", text)).strip()


def spoken_list(items: list[str]) -> str:
    if len(items) < 3:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def call_script(store: dict, exam: str, time: str | None) -> str:
    """What Cubbie says on the exam-morning call: about 30 seconds, the Direct hints first."""
    groups = grouped(store)
    direct = [speakable(g["concept"]) for g in groups if g["rank"] == "direct"][:3]
    only = [speakable(g["concept"]) for g in groups if g["status"] == "only_lecture" and g["rank"] in ("strong", "repeated")][:2]
    skips = [speakable(g["concept"]) for g in groups if g["rank"] == "skip"][:1]
    course = speakable(store["course"])
    parts = [f"Good morning. This is your Front Row wake-up call for {course}.",
             f"Your {exam} is {f'at {time}' if time else 'today'}."]
    if direct:
        count = {1: "one thing", 2: "two things", 3: "three things"}[len(direct)]
        parts.append(f"Your professor said {count} straight out: {spoken_list(direct)}.")
    if only:
        parts.append(f"Only said in lecture, not in the slides: {spoken_list(only)}.")
    if skips:
        parts.append(f"And remember, {skips[0]} is not on the exam.")
    if not (direct or only):
        parts.append("No direct hints were saved for this class, so trust your studying.")
    parts.append("Your full list is in your texts. You've got this.")
    return " ".join(parts)


# ---------------------------------------------------------------- export


def export_markdown(store: dict, exam: str | None, date: str | None, transcript: str | None) -> str:
    """A Markdown file the student can save or paste into any AI model: context, hints, sources, prompts."""
    hints = [h for h in store["hints"] if not date or h["date"] == date]
    if not hints:
        fail(f"No hints saved for {store['course']}{' on ' + date if date else ''}.", 3)
    view = {**store, "hints": hints}
    groups = grouped(view)
    dates = sorted({h["date"] for h in hints})
    rated = [g for g in groups if g["rank"] != "skip"]
    scope = f"the {date} lecture" if date else f"{len(dates)} lecture{'s' if len(dates) != 1 else ''} ({dates[0]} to {dates[-1]})"
    if len(dates) == 1 and not date:
        scope = f"1 lecture ({dates[0]})"

    out = [f"# {store['course']}: Front Row lecture notes", ""]
    out.append(f"{len(rated)} exam hints from {scope}"
               f"{f', for the {exam}' if exam else ''}, caught by Front Row from my own lecture recordings.")
    out += ["", "## How to use this file", "",
            "Paste or upload it into ChatGPT, Claude, Gemini or any AI model, then try:", "",
            "- Quiz me on the Direct hints, one question at a time, and wait for my answer.",
            "- Make a one-page study guide from these hints, Direct first.",
            "- Explain each hint marked \"only said in lecture\" like I missed that class.",
            "- Write practice problems in the style the professor described.", "",
            "## What the labels mean", "",
            "- **Direct**: the professor said it will be on the exam, or \"you need to know this\".",
            "- **Strong**: \"this is important\", \"write this down\", \"people always get this wrong\".",
            "- **Repeated**: the professor came back to it 3 or more times in one lecture.",
            "- **In the slides** / **Only said in lecture** / **Not checked**: whether it was found in the course "
            "materials. Not checked means the slides weren't searched, not that it's missing.", "",
            "These are what the professor said, not a promise of what's on the exam.", ""]

    for rank in ("direct", "strong", "repeated"):
        items = [g for g in groups if g["rank"] == rank]
        if not items:
            continue
        out += [f"## {rank.capitalize()}", ""]
        for g in items:
            out.append(f"### {g['concept']}")
            out.append("")
            for h in sorted((h for h in hints if h["concept"].casefold() == g["concept"].casefold()), key=lambda h: h["date"]):
                minute = f", minute {h['minute']}" if h.get("minute") not in (None, "") else ""
                said = f": \"{h['quote']}\"" if h.get("quote") else ""
                out.append(f"- {h['date']}{minute}{said}")
            if g["status"] == "slides":
                spot = g.get("link") or g.get("material")
                out.append(f"- In the slides{f': {spot}' if spot else ''}")
            else:
                out.append(f"- {'Only said in lecture' if g['status'] == 'only_lecture' else 'Not checked against the slides'}")
            out.append("")

    skips = [g for g in groups if g["rank"] == "skip"]
    if skips:
        out += ["## Said NOT on the exam", ""] + [f"- {g['concept']}" for g in skips] + [""]

    if len(dates) > 1:
        out += ["## By lecture", ""]
        for d in dates:
            names = [f"{h['concept']} ({h['rank']})" for h in hints if h["date"] == d]
            out.append(f"- **{d}**: {', '.join(names)}")
        out.append("")

    if transcript:
        out += ["## Transcript", "", transcript.strip(), ""]
    return "\n".join(out)


# ---------------------------------------------------------------- main


def sample_store() -> dict:
    store = {"course": "BIO 181 (sample)", "hints": []}
    add_hints(store, match(read_json(SAMPLE_HINTS), SAMPLE_MATERIALS)["hints"], "2026-10-21")
    return store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="candidate hint moments in a transcript")
    p.add_argument("--transcript", type=Path)
    p.add_argument("--json", action="store_true")
    p.add_argument("--sample", action="store_true")

    p = sub.add_parser("match", help="check hints against course materials")
    p.add_argument("--hints", type=Path)
    p.add_argument("--materials", type=Path)
    p.add_argument("--out", type=Path, help="write the checked hints here as JSON")
    p.add_argument("--json", action="store_true")
    p.add_argument("--sample", action="store_true")

    p = sub.add_parser("save", help="add a lecture's hints to the class list")
    p.add_argument("--course")
    p.add_argument("--date", help="lecture date, YYYY-MM-DD, in the student's time zone")
    p.add_argument("--hints", type=Path)
    p.add_argument("--sample", action="store_true", help="show what would be saved; saves nothing")

    p = sub.add_parser("list", help="the class's running list")
    p.add_argument("--course")
    p.add_argument("--short", action="store_true", help="night-before list: direct and only-in-lecture")
    p.add_argument("--json", action="store_true")
    p.add_argument("--sample", action="store_true")

    p = sub.add_parser("pdf", help="one-page PDF of the class list")
    p.add_argument("--course")
    p.add_argument("--exam", default="Exam")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--checks", type=Path, help='JSON {"concept": "self-check question"} for direct hints')
    p.add_argument("--sample", action="store_true")

    p = sub.add_parser("call", help="what to say on the exam-morning wake-up call")
    p.add_argument("--course")
    p.add_argument("--exam", default="exam")
    p.add_argument("--time", help='exam start time as the student would say it, for example "10 AM"')
    p.add_argument("--sample", action="store_true")

    p = sub.add_parser("export", help="Markdown file of the hints, ready for any AI model")
    p.add_argument("--course")
    p.add_argument("--exam", help="exam name to put in the header")
    p.add_argument("--date", help="only this lecture, YYYY-MM-DD")
    p.add_argument("--transcript", type=Path, help="append this lecture's transcript (use with --date)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--sample", action="store_true")

    sub.add_parser("courses", help="classes with saved hints")

    args = parser.parse_args(argv)

    if args.command == "scan":
        path = SAMPLE_TRANSCRIPT if args.sample else args.transcript
        if not path:
            fail("Pass --transcript FILE (or --sample).")
        result = scan(read_text(path))
        emit(json.dumps(result, indent=1) if args.json else format_scan(result))

    elif args.command == "match":
        hints_path = SAMPLE_HINTS if args.sample else args.hints
        folder = SAMPLE_MATERIALS if args.sample else args.materials
        if not hints_path or not folder:
            fail("Pass --hints FILE and --materials DIR (or --sample).")
        if not folder.is_dir():
            fail(f"{folder} is not a folder. Download the class's slides and pages into one first.")
        hints = read_json(hints_path)
        if not isinstance(hints, list):
            fail("--hints must be a JSON list of hints.")
        result = match(hints, folder)
        if args.out:
            args.out.write_text(json.dumps(result["hints"], indent=1, ensure_ascii=False))
        emit(json.dumps(result, indent=1) if args.json else format_match(result))

    elif args.command == "save":
        if args.sample:
            store = sample_store()
            emit("Sample only, nothing saved.\n\n" + format_list(store, short=False))
            return 0
        if not (args.course and args.date and args.hints):
            fail("Pass --course, --date YYYY-MM-DD and --hints FILE.")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
            fail("--date must look like 2026-10-21.")
        hints = read_json(args.hints)
        if not isinstance(hints, list):
            fail("--hints must be a JSON list of hints.")
        store = load_course(args.course)
        added, replaced = add_hints(store, hints, args.date)
        save_course(store)
        print(f"Saved {added} new and {replaced} updated hint(s) for {store['course']} ({args.date}). "
              f"{len(store['hints'])} saved in all.")

    elif args.command in {"list", "pdf", "call", "export"}:
        if args.sample:
            store = sample_store()
        else:
            if not args.course:
                fail("Pass --course (or --sample).")
            store = load_course(args.course)
            if not store["hints"]:
                fail(f"No hints saved for {args.course} yet.", 3)
        if args.command == "list":
            emit(json.dumps(grouped(store), indent=1, ensure_ascii=False) if args.json else format_list(store, args.short))
        elif args.command == "call":
            print(call_script(store, args.exam, args.time))
        elif args.command == "export":
            path = args.transcript or (SAMPLE_TRANSCRIPT if args.sample else None)
            transcript = read_text(path) if path else None
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(export_markdown(store, args.exam, args.date, transcript), encoding="utf-8")
            print(f"Wrote {args.out}")
        else:
            checks = read_json(args.checks) if args.checks else {}
            render_pdf(store, args.exam, args.out, checks)
            print(f"Wrote {args.out}")

    elif args.command == "courses":
        files = sorted(data_dir().glob("*.json")) if data_dir().exists() else []
        if not files:
            fail("No classes saved yet.", 3)
        for path in files:
            store = read_json(path)
            print(f"{store['course']}: {len(store['hints'])} hints")
    return 0


if __name__ == "__main__":
    sys.exit(main())
