"""Report generation for the Job Posting Analyzer web app.

One analysis result can be exported in several formats:
    Markdown, PDF, Word (.docx), charts (PNG) and spoken audio (text-to-speech).

The user chooses which sections to include; every format uses the same selection.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date

import matplotlib
matplotlib.use("Agg")  # render charts without a display
import matplotlib.pyplot as plt
import pandas as pd

SECTIONS = ["Summary", "Skills table", "Charts", "Strengths", "Gaps to close", "Resume tips", "Interview prep"]
FORMATS = {
    "PDF": "Formatted document to print or share",
    "Word (.docx)": "Editable document",
    "Markdown": "Plain text with formatting, easy to paste",
    "Audio (text-to-speech)": "Listen to a spoken summary",
    "Charts (PNG)": "Skill coverage and market demand graphs",
}
BLUE, ORANGE, GREY, INK, MUTED = "#2a78d6", "#eb6834", "#c9c8c3", "#1b1b1a", "#5b5a56"


# ---------------------------------------------------------------- shared content
def pay_text(posting) -> str:
    if not (posting.salary_min or posting.salary_max):
        return "Not listed"
    unit = "per hour" if posting.pay_period == "hour" else "per year"
    lo, hi = posting.salary_min, posting.salary_max
    return f"${lo:,.0f} - ${hi:,.0f} {unit}" if lo and hi else f"${(lo or hi):,.0f} {unit}"


def skills_rows(table: pd.DataFrame) -> list[list[str]]:
    """Skill table rows with plain-text yes/no (emoji don't render in every PDF font)."""
    return [[r.iloc[0], "Yes" if r.iloc[1] == "✅" else "No", r.iloc[2]] for _, r in table.iterrows()]


def sorted_gaps(recs):
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(recs.gaps, key=lambda g: order[g.priority])


def file_stem(posting) -> str:
    return "report_" + re.sub(r"[^A-Za-z0-9]+", "_", f"{posting.company}_{posting.job_title}").strip("_")[:60]


# ---------------------------------------------------------------- charts
def _style(ax, title):
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=10)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#d0d0cc")
    ax.tick_params(colors=MUTED, length=0)
    ax.grid(axis="x", color="#ececea", linewidth=0.8)
    ax.set_axisbelow(True)


def coverage_chart(posting, my_skills: list[str]):
    """Stacked bars: how many required / nice-to-have skills the candidate has vs. is missing."""
    mine = {s.lower() for s in my_skills}
    groups = [("Required", posting.required_skills), ("Nice to have", posting.nice_to_have_skills)]
    have = [sum(s.lower() in mine for s in lst) for _, lst in groups]
    miss = [len(lst) - h for (_, lst), h in zip(groups, have)]
    fig, ax = plt.subplots(figsize=(7, 2.4))
    labels = [g for g, _ in groups][::-1]
    ax.barh(labels, have[::-1], color=BLUE, height=0.5, label="You have it")
    ax.barh(labels, miss[::-1], left=have[::-1], color=ORANGE, height=0.5, label="Missing")
    for y, (h, m) in enumerate(zip(have[::-1], miss[::-1])):
        if h + m:
            ax.text(h + m + 0.1, y, f"{h} of {h + m}", va="center", fontsize=9, color=MUTED)
    ax.set_xlim(0, max([h + m for h, m in zip(have, miss)] + [1]) * 1.25)
    ax.xaxis.get_major_locator().set_params(integer=True)
    ax.set_xlabel("Number of skills", color=MUTED)
    ax.legend(frameon=False, loc="lower right", fontsize=8)
    _style(ax, "Skill coverage for this posting")
    fig.tight_layout()
    return fig


def demand_chart(posting, my_skills: list[str], market: pd.Series):
    """How common each of this posting's skills is across the sample, coloured by whether the candidate has it."""
    mine = {s.lower() for s in my_skills}
    lookup = {k.lower(): v for k, v in market.items()}
    skills = list(dict.fromkeys(posting.required_skills + posting.nice_to_have_skills))
    if not skills or not lookup:
        return None
    data = sorted(((s, lookup.get(s.lower(), 0.0), s.lower() in mine) for s in skills), key=lambda x: x[1])
    fig, ax = plt.subplots(figsize=(7, 0.42 * len(data) + 1.2))
    ax.barh([d[0] for d in data], [d[1] for d in data], height=0.6,
            color=[BLUE if d[2] else ORANGE for d in data])
    for y, d in enumerate(data):
        ax.text(d[1] + 1, y, f"{d[1]:.0f}%", va="center", fontsize=8.5, color=MUTED)
    ax.set_xlim(0, 110)
    ax.set_xlabel("% of sample postings that require this skill", color=MUTED)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=BLUE, label="You have it"), Patch(color=ORANGE, label="Missing")],
              frameon=False, loc="lower right", fontsize=8)
    _style(ax, "How in-demand this posting's skills are")
    fig.tight_layout()
    return fig


def fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200)
    plt.close(fig)
    return buf.getvalue()


def chart_pngs(posting, my_skills, market) -> dict[str, bytes]:
    out = {"skill_coverage.png": fig_to_png(coverage_chart(posting, my_skills))}
    d = demand_chart(posting, my_skills, market)
    if d is not None:
        out["skill_demand.png"] = fig_to_png(d)
    return out


# ---------------------------------------------------------------- Markdown
def to_markdown(posting, recs, table, sections, market=None, my_skills=None) -> str:
    L = [f"# {posting.job_title} at {posting.company}", f"*Generated {date.today():%B %d, %Y}*", ""]
    if "Summary" in sections:
        L += ["## Summary", "", f"**Verdict:** {recs.verdict}  ", f"**Fit score:** {recs.fit_score}/100 (AI estimate)  ",
              f"**Seniority:** {posting.seniority} · **Work mode:** {posting.work_mode} · "
              f"**Min. experience:** {posting.min_years_experience if posting.min_years_experience is not None else 'not stated'} · "
              f"**Pay:** {pay_text(posting)}", "", recs.fit_summary, ""]
    if "Skills table" in sections:
        L += ["## Required skills", "", "| Skill | You have it | % of sample postings |", "|---|---|---|"]
        L += [f"| {a} | {b} | {c} |" for a, b, c in skills_rows(table)]
        if posting.nice_to_have_skills:
            L += ["", "**Nice to have:** " + ", ".join(posting.nice_to_have_skills)]
        L += [""]
    if "Strengths" in sections and recs.strengths:
        L += ["## Strengths", ""] + [f"- {s}" for s in recs.strengths] + [""]
    if "Gaps to close" in sections:
        L += ["## Gaps to close", ""]
        L += [f"- **{g.skill}** ({g.priority} priority): {g.why_it_matters} *How to close it:* {g.how_to_close}"
              for g in sorted_gaps(recs)] or ["- No significant gaps found."]
        L += [""]
    if "Resume tips" in sections and recs.resume_tips:
        L += ["## Resume tips", ""] + [f"- {t}" for t in recs.resume_tips] + [""]
    if "Interview prep" in sections and recs.interview_topics:
        L += ["## Interview prep", ""] + [f"- {t}" for t in recs.interview_topics] + [""]
    if "Charts" in sections:
        L += ["*Charts are available in the PDF, Word and PNG versions of this report.*", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- PDF
def _register_pdf_font():
    """Use a Unicode TrueType font if one is installed (macOS or Linux), otherwise Helvetica."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.fonts import addMapping
    candidates = [
        ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", None),
        ("/Library/Fonts/Arial Unicode.ttf", None),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for regular, bold in candidates:
        if os.path.exists(regular):
            try:
                pdfmetrics.registerFont(TTFont("RptSans", regular))
                pdfmetrics.registerFont(TTFont("RptSans-Bold", bold if bold and os.path.exists(bold) else regular))
                addMapping("RptSans", 0, 0, "RptSans"); addMapping("RptSans", 1, 0, "RptSans-Bold")
                addMapping("RptSans", 0, 1, "RptSans"); addMapping("RptSans", 1, 1, "RptSans-Bold")
                return "RptSans", "RptSans-Bold", True
            except Exception:
                continue
    return "Helvetica", "Helvetica-Bold", False


def to_pdf(posting, recs, table, sections, market, my_skills) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

    font, bold, unicode_ok = _register_pdf_font()

    def t(s):  # escape for reportlab markup; drop characters Helvetica can't draw
        s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return s if unicode_ok else s.encode("latin-1", "replace").decode("latin-1")

    ink, muted, accent, soft, rule = (colors.HexColor(c) for c in ("#1b1b1a", "#5b5a56", "#2a78d6", "#f4f3ef", "#d9d8d3"))
    body = ParagraphStyle("b", fontName=font, fontSize=10, leading=14.5, textColor=ink, spaceAfter=6)
    small = ParagraphStyle("s", parent=body, fontSize=8.5, leading=11.5, textColor=muted)
    h1 = ParagraphStyle("h1", fontName=bold, fontSize=19, leading=24, textColor=ink, spaceAfter=4)
    h2 = ParagraphStyle("h2", fontName=bold, fontSize=12.5, leading=16, textColor=ink, spaceBefore=12, spaceAfter=6, keepWithNext=1)
    bullet = ParagraphStyle("li", parent=body, leftIndent=14, bulletIndent=3, spaceAfter=3, bulletFontName=font)
    cell = ParagraphStyle("c", parent=body, fontSize=9, leading=12, spaceAfter=0)
    callout = ParagraphStyle("co", parent=body, backColor=colors.HexColor("#eaf2fc"), borderPadding=(8, 9, 8, 9),
                             leftIndent=9, rightIndent=9, spaceBefore=4, spaceAfter=12)
    W = letter[0] - 1.6 * inch

    def tbl(rows, widths):
        data = [[Paragraph(("<b>%s</b>" % t(c)) if i == 0 else t(c), cell) for c in row] for i, row in enumerate(rows)]
        tb = Table(data, colWidths=widths, repeatRows=1)
        tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), soft), ("LINEBELOW", (0, 0), (-1, 0), 0.8, muted),
                                ("LINEBELOW", (0, 1), (-1, -1), 0.4, rule), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return tb

    def img(png: bytes, width=W):
        from PIL import Image as PI
        w, h = PI.open(io.BytesIO(png)).size
        return Image(io.BytesIO(png), width=width, height=width * h / w)

    S = [Paragraph(t(f"{posting.job_title} at {posting.company}"), h1),
         Paragraph(t(f"Job Posting Analyzer report · generated {date.today():%B %d, %Y}"), small), Spacer(1, 8)]
    if "Summary" in sections:
        S += [Paragraph(f"<b>{t(recs.verdict)}</b> · fit score {recs.fit_score}/100 (AI estimate)<br/>{t(recs.fit_summary)}", callout),
              tbl([["Seniority", "Work mode", "Min. experience", "Pay"],
                   [posting.seniority.title(), posting.work_mode.title(),
                    f"{posting.min_years_experience} yrs" if posting.min_years_experience is not None else "Not stated",
                    pay_text(posting)]], [W / 4] * 4)]
    if "Skills table" in sections:
        S += [Paragraph("Required skills", h2)]
        rows = skills_rows(table)
        S += [tbl([["Skill", "You have it", "% of sample postings requiring it"]] + rows, [W * 0.4, W * 0.2, W * 0.4])] if rows \
            else [Paragraph("No required skills were found in this posting.", body)]
        if posting.nice_to_have_skills:
            S += [Spacer(1, 6), Paragraph("<b>Nice to have:</b> " + t(", ".join(posting.nice_to_have_skills)), body)]
    if "Charts" in sections:
        pngs = chart_pngs(posting, my_skills, market)
        S += [Paragraph("Charts", h2)] + [KeepTogether([img(p, W * 0.85), Spacer(1, 8)]) for p in pngs.values()]
    if "Strengths" in sections and recs.strengths:
        S += [Paragraph("Strengths", h2)] + [Paragraph(t(s), bullet, bulletText="•") for s in recs.strengths]
    if "Gaps to close" in sections:
        S += [Paragraph("Gaps to close", h2)]
        gaps = sorted_gaps(recs)
        S += [tbl([["Skill", "Priority", "Why it matters", "How to close it"]] +
                  [[g.skill, g.priority.title(), g.why_it_matters, g.how_to_close] for g in gaps],
                  [W * 0.16, W * 0.12, W * 0.33, W * 0.39])] if gaps else [Paragraph("No significant gaps found.", body)]
    if "Resume tips" in sections and recs.resume_tips:
        S += [Paragraph("Resume tips", h2)] + [Paragraph(t(x), bullet, bulletText="•") for x in recs.resume_tips]
    if "Interview prep" in sections and recs.interview_topics:
        S += [Paragraph("Interview prep", h2)] + [Paragraph(t(x), bullet, bulletText="•") for x in recs.interview_topics]

    def footer(c, d):
        c.saveState(); c.setFont(font, 7.5); c.setFillColor(muted)
        c.drawString(0.8 * inch, 0.5 * inch, "Job Posting Analyzer · AI-generated recommendations; verify before relying on them")
        c.drawRightString(letter[0] - 0.8 * inch, 0.5 * inch, f"Page {d.page}")
        c.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch, topMargin=0.75 * inch,
                      bottomMargin=0.8 * inch, title=f"{posting.job_title} at {posting.company}",
                      author="Job Posting Analyzer").build(S, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ---------------------------------------------------------------- Word
def to_docx(posting, recs, table, sections, market, my_skills) -> bytes:
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    doc.styles["Normal"].font.size = Pt(10.5)
    doc.add_heading(f"{posting.job_title} at {posting.company}", level=0)
    p = doc.add_paragraph(f"Job Posting Analyzer report · generated {date.today():%B %d, %Y}")
    p.runs[0].font.color.rgb = RGBColor(0x5B, 0x5A, 0x56)

    def add_table(rows):
        tb = doc.add_table(rows=len(rows), cols=len(rows[0]))
        tb.style = "Light Grid Accent 1"
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                tb.cell(i, j).text = str(val)
                if i == 0:
                    for r in tb.cell(i, j).paragraphs[0].runs:
                        r.bold = True
        doc.add_paragraph()

    if "Summary" in sections:
        doc.add_heading("Summary", level=1)
        p = doc.add_paragraph(); p.add_run(recs.verdict).bold = True
        p.add_run(f" · fit score {recs.fit_score}/100 (AI estimate)")
        doc.add_paragraph(recs.fit_summary)
        add_table([["Seniority", "Work mode", "Min. experience", "Pay"],
                   [posting.seniority.title(), posting.work_mode.title(),
                    f"{posting.min_years_experience} yrs" if posting.min_years_experience is not None else "Not stated",
                    pay_text(posting)]])
    if "Skills table" in sections:
        doc.add_heading("Required skills", level=1)
        rows = skills_rows(table)
        if rows:
            add_table([["Skill", "You have it", "% of sample postings requiring it"]] + rows)
        if posting.nice_to_have_skills:
            p = doc.add_paragraph(); p.add_run("Nice to have: ").bold = True
            p.add_run(", ".join(posting.nice_to_have_skills))
    if "Charts" in sections:
        doc.add_heading("Charts", level=1)
        for png in chart_pngs(posting, my_skills, market).values():
            doc.add_picture(io.BytesIO(png), width=Inches(6))
    if "Strengths" in sections and recs.strengths:
        doc.add_heading("Strengths", level=1)
        for s in recs.strengths:
            doc.add_paragraph(s, style="List Bullet")
    if "Gaps to close" in sections:
        doc.add_heading("Gaps to close", level=1)
        gaps = sorted_gaps(recs)
        if gaps:
            add_table([["Skill", "Priority", "Why it matters", "How to close it"]] +
                      [[g.skill, g.priority.title(), g.why_it_matters, g.how_to_close] for g in gaps])
        else:
            doc.add_paragraph("No significant gaps found.")
    if "Resume tips" in sections and recs.resume_tips:
        doc.add_heading("Resume tips", level=1)
        for x in recs.resume_tips:
            doc.add_paragraph(x, style="List Bullet")
    if "Interview prep" in sections and recs.interview_topics:
        doc.add_heading("Interview prep", level=1)
        for x in recs.interview_topics:
            doc.add_paragraph(x, style="List Bullet")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- text-to-speech
def speech_script(posting, recs, table, sections) -> str:
    """A spoken version of the report: full sentences, no tables or symbols."""
    def join(items):
        items = list(items)
        return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
    parts = [f"Job posting report for {posting.job_title} at {posting.company}."]
    if "Summary" in sections:
        parts.append(f"The verdict is: {recs.verdict.replace(':', ',')}. The estimated fit score is {recs.fit_score} out of 100.")
        parts.append(recs.fit_summary)
        exp = f"at least {posting.min_years_experience} years of experience" if posting.min_years_experience is not None \
            else "no stated minimum experience"
        article = "an" if posting.seniority[0] in "aeiou" else "a"
        parts.append(f"This is {article} {posting.seniority}-level, {posting.work_mode} role with {exp}.")
        if posting.salary_min or posting.salary_max:
            unit = "per hour" if posting.pay_period == "hour" else "per year"
            lo, hi = posting.salary_min, posting.salary_max
            amount = f"{lo:,.0f} to {hi:,.0f}" if lo and hi else f"{(lo or hi):,.0f}"
            parts.append(f"Pay is {amount} dollars {unit}.")
        else:
            parts.append("Pay is not listed.")
    if "Skills table" in sections and len(table):
        rows = skills_rows(table)
        have = [r[0] for r in rows if r[1] == "Yes"]
        missing = [r[0] for r in rows if r[1] == "No"]
        parts.append(f"You have {len(have)} of the {len(rows)} required skills.")
        if have:
            parts.append(f"You already have {join(have)}.")
        if missing:
            parts.append(f"You are missing {join(missing)}.")
    if "Strengths" in sections and recs.strengths:
        parts.append("Your strengths for this role. " + " ".join(recs.strengths[:3]))
    if "Gaps to close" in sections and recs.gaps:
        parts.append("Gaps to close.")
        for g in sorted_gaps(recs)[:3]:
            parts.append(f"{g.skill}, {g.priority} priority. {g.how_to_close}")
    if "Resume tips" in sections and recs.resume_tips:
        parts.append("Resume tips. " + " ".join(recs.resume_tips[:3]))
    if "Interview prep" in sections and recs.interview_topics:
        parts.append("To prepare for the interview, focus on: " + " ".join(recs.interview_topics[:3]))
    parts.append("End of report.")
    text = " ".join(p.strip() for p in parts if p and p.strip())
    text = re.sub(r"[*_`#|>]", "", text)              # strip any markdown symbols
    return re.sub(r"\s+", " ", text).strip()


def tts_engines() -> list[str]:
    engines = []
    if sys.platform == "darwin" and shutil.which("say"):
        engines.append("macOS voice (offline)")
    try:
        import gtts  # noqa: F401
        engines.append("Google TTS (online)")
    except ImportError:
        pass
    return engines


def mac_voices() -> list[str]:
    """English voices installed on this Mac (empty list elsewhere)."""
    if not (sys.platform == "darwin" and shutil.which("say")):
        return []
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
        return [line.split()[0] for line in out.splitlines() if "en_" in line and line.split()]
    except Exception:
        return []


def to_audio(text: str, engine: str, voice: str | None = None, rate: int = 185) -> tuple[bytes, str, str]:
    """Return (audio bytes, mime type, file extension)."""
    if engine.startswith("macOS"):
        with tempfile.TemporaryDirectory() as d:
            src, aiff, m4a = (os.path.join(d, n) for n in ("in.txt", "out.aiff", "out.m4a"))
            with open(src, "w") as f:
                f.write(text)
            cmd = ["say", "-r", str(rate), "-f", src, "-o", aiff] + (["-v", voice] if voice else [])
            subprocess.run(cmd, check=True, timeout=180)
            # AIFF only plays in Safari; convert to AAC (.m4a) with macOS's built-in afconvert so every browser can play it
            if shutil.which("afconvert"):
                subprocess.run(["afconvert", aiff, m4a, "-f", "m4af", "-d", "aac"], check=True, timeout=120)
                return open(m4a, "rb").read(), "audio/mp4", "m4a"
            return open(aiff, "rb").read(), "audio/aiff", "aiff"
    from gtts import gTTS
    buf = io.BytesIO()
    gTTS(text=text, lang="en").write_to_fp(buf)
    return buf.getvalue(), "audio/mpeg", "mp3"
