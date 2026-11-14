"""Shared logic for the job posting analyzer web app (app.py).

Reads uploaded posting files, calls Gemini for structured extraction and
recommendations, and compares the posting with the 20-posting dataset.
"""
from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

load_dotenv(override=True)

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
POSTINGS_DIR = Path("postings")
CACHE_FILE = Path("data/extracted.json")
SOURCES_FILE = Path("sources.csv")


# ---------------------------------------------------------------- schemas
class JobPosting(BaseModel):
    job_title: str
    company: str
    seniority: Literal["intern", "entry", "mid", "senior", "lead"] = Field(
        description="Infer from title and years of experience: 0-1 yrs entry, 2-4 mid, 5+ senior.")
    work_mode: Literal["remote", "hybrid", "onsite", "unspecified"]
    min_years_experience: Optional[int] = Field(description="Minimum years required; null if not stated.")
    required_skills: list[str] = Field(description="Technical skills and tools listed as required.")
    nice_to_have_skills: list[str] = Field(description="Skills listed as preferred, a plus, or nice to have.")
    salary_min: Optional[float] = Field(description="Lower bound of pay as stated; null if not stated.")
    salary_max: Optional[float] = Field(description="Upper bound of pay as stated; null if not stated.")
    pay_period: Literal["year", "hour", "unspecified"]


class SkillGap(BaseModel):
    skill: str
    priority: Literal["high", "medium", "low"] = Field(
        description="high = required and common in the market; low = nice-to-have or rare.")
    why_it_matters: str = Field(description="One sentence on how this role uses the skill.")
    how_to_close: str = Field(description="A concrete, specific way to build or demonstrate this skill, e.g. a small project.")


class Recommendations(BaseModel):
    verdict: Literal["Strong fit: apply now", "Good fit: apply and address gaps", "Stretch: build skills first"]
    fit_score: int = Field(description="Overall fit from 0 to 100.")
    fit_summary: str = Field(description="2-3 sentences explaining the verdict, addressed to the candidate as 'you'.")
    strengths: list[str] = Field(description="What the candidate already offers for this role, each tied to the posting.")
    gaps: list[SkillGap] = Field(description="Missing skills, most important first.")
    resume_tips: list[str] = Field(description="Specific changes to the resume for this posting.")
    interview_topics: list[str] = Field(description="Topics or question types to prepare for this role.")


class ResumeProfile(BaseModel):
    skills: list[str] = Field(description="Technical skills, tools and methods the resume shows, as canonical names.")
    years_experience: Optional[float] = Field(
        description="Total years of professional work experience; null if unclear. Internships/co-ops count as their duration.")
    education: list[str] = Field(description="Degrees and certificates, e.g. 'MS Data Science (in progress, 2027)'.")
    experience_summary: str = Field(description="2-3 sentences summarizing the candidate's experience, written to them as 'you'.")


class MarketReview(BaseModel):
    readiness_summary: str = Field(description="2-3 sentences on how ready the candidate is for this set of roles, addressed as 'you'.")
    top_priorities: list[SkillGap] = Field(description="The skills that would raise the candidate's match across the most postings, most important first.")
    resume_improvements: list[str] = Field(description="Specific edits to the resume itself (wording, missing keywords the candidate genuinely has, structure).")
    best_fit_roles: list[str] = Field(description="Which of the listed postings fit best and why, one short line each.")


EXTRACT_PROMPT = """You extract structured information from job postings.
Rules:
- Skills are technical skills, tools, platforms or methods (not soft skills like "communication").
- Use short canonical names: "SQL", "Python", "R", "Excel", "Google Sheets", "Tableau", "Power BI",
  "Looker", "Snowflake", "dbt", "BigQuery", "Redshift", "Databricks", "Statistics", "A/B Testing",
  "Machine Learning", "Git", "AWS", "Data Modeling". Do not include version numbers or extra words.
- If a posting says "X or Y" (e.g. "Tableau or Power BI"), list each tool separately.
- Only put a skill in nice_to_have_skills if the posting marks it preferred / a plus / nice to have.
- Use null for anything not stated. Never guess salary or years of experience."""

RECOMMEND_PROMPT = """You are a practical career coach for data analytics roles.
You get a structured job posting, the candidate's skills and background, and how often each skill
appears across a sample of similar postings. Give honest, specific recommendations:
- Base the verdict and fit_score on required skills, experience level and seniority, not on nice-to-haves.
- Do not invent experience the candidate didn't mention. If the background is empty, judge on skills only.
- Each gap's how_to_close must be concrete (a project idea, a specific practice task, a certification),
  sized for someone studying while job hunting.
- Resume tips should name the posting's own keywords where the candidate genuinely has the skill.
- Keep every list to at most 5 items."""


RESUME_PROMPT = """You extract a structured profile from a resume.
- List every technical skill, tool, platform or method the resume shows (in a skills section, projects or job duties).
- Use the same short canonical names as job postings: "SQL", "Python", "R", "Excel", "Google Sheets", "Tableau",
  "Power BI", "Looker", "Snowflake", "dbt", "BigQuery", "Redshift", "Databricks", "Statistics", "A/B Testing",
  "Machine Learning", "Git", "AWS", "Data Modeling". No version numbers, no soft skills.
- Only include what the resume actually states. Do not infer skills that aren't there."""

MARKET_PROMPT = """You are a practical career coach for data analytics roles. You get a candidate's resume,
their skills, a ranked list of real job postings with how many required skills they match, and the skills
they are missing most often across those postings. Give honest, specific advice:
- top_priorities must come from the missing-skills data; rank by how many postings each skill would unlock.
- Each how_to_close must be concrete and sized for someone studying while job hunting (a project, a course, a certification).
- resume_improvements are edits to the resume text itself; only suggest adding keywords the candidate genuinely has.
- Do not invent experience. Keep every list to at most 5 items."""


# ---------------------------------------------------------------- file reading
def read_posting_file(filename: str, data: bytes) -> str:
    """Return the text of an uploaded .txt, .md, .pdf or .docx file."""
    ext = Path(filename).suffix.lower()
    if ext in {".txt", ".md"}:
        for enc in ("utf-8", "utf-16", "latin-1"):
            try:
                return data.decode(enc).strip()
            except UnicodeDecodeError:
                continue
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if ext == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(parts).strip()
    raise ValueError(f"Unsupported file type: {ext}. Use .txt, .md, .pdf or .docx.")


# ---------------------------------------------------------------- Gemini calls
def get_client() -> genai.Client:
    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY not found. Add it to the .env file in the project folder.")
    return genai.Client()


def _structured_call(client, model: str, system: str, contents: str, schema: type[BaseModel]):
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_json_schema=schema.model_json_schema(),
        temperature=0,
    )
    # Retry temporary errors (rate limits, overloaded model, server errors) with growing waits.
    # Errors that won't fix themselves (bad key, unknown model) are raised immediately.
    waits = [3, 8, 20]
    for attempt in range(len(waits) + 1):
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            return schema.model_validate_json(response.text)
        except Exception as e:
            code = getattr(e, "code", None)
            temporary = code in (429, 500, 502, 503, 504) or "UNAVAILABLE" in str(e)
            if not temporary or attempt == len(waits):
                raise
            time.sleep(waits[attempt])


def extract_posting(client, model: str, text: str) -> JobPosting:
    return _structured_call(client, model, EXTRACT_PROMPT, text, JobPosting)


def extract_resume(client, model: str, text: str) -> ResumeProfile:
    return _structured_call(client, model, RESUME_PROMPT, text[:15000], ResumeProfile)


def recommend(client, model: str, posting: JobPosting, my_skills: list[str],
              background: str, market: pd.Series, resume_text: str = "") -> Recommendations:
    skills_in_posting = posting.required_skills + posting.nice_to_have_skills
    market_lines = "\n".join(f"- {s}: required in {market.get(s, 0):.0f}% of sample postings"
                             for s in skills_in_posting) or "(no market data)"
    contents = f"""JOB POSTING (structured):
{posting.model_dump_json(indent=2)}

CANDIDATE SKILLS: {", ".join(my_skills) if my_skills else "(none listed)"}

CANDIDATE BACKGROUND: {background.strip() or "(not provided)"}

HOW COMMON EACH SKILL IS IN SIMILAR POSTINGS:
{market_lines}"""
    if resume_text:
        contents += f"\n\nCANDIDATE RESUME:\n{resume_text[:8000]}"
    return _structured_call(client, model, RECOMMEND_PROMPT, contents, Recommendations)


def review_against_market(client, model: str, my_skills: list[str], resume_text: str,
                          ranked: pd.DataFrame, missing: pd.DataFrame) -> MarketReview:
    postings = "\n".join(
        f"- {r.company}: {r.job_title} ({r.seniority}) matches {r.matched}/{r.required} required skills; missing: {r.missing or 'none'}"
        for r in ranked.itertuples())
    gaps = "\n".join(f"- {r.skill}: required in {r.pct:.0f}% of postings" for r in missing.head(10).itertuples())
    contents = f"""CANDIDATE SKILLS: {", ".join(my_skills) or "(none)"}

POSTINGS RANKED BY MATCH:
{postings}

SKILLS THE CANDIDATE IS MISSING, BY HOW OFTEN POSTINGS REQUIRE THEM:
{gaps or "(none)"}

CANDIDATE RESUME:
{resume_text[:8000] or "(not provided)"}"""
    return _structured_call(client, model, MARKET_PROMPT, contents, MarketReview)


# ---------------------------------------------------------------- dataset helpers
def market_skill_pct() -> pd.Series:
    """% of cached dataset postings that list each skill as required (empty if no cache yet)."""
    if not CACHE_FILE.exists():
        return pd.Series(dtype=float)
    records = json.loads(CACHE_FILE.read_text())
    if not records:
        return pd.Series(dtype=float)
    counts: dict[str, int] = {}
    casing: dict[str, str] = {}
    for r in records:
        for s in {x.strip().lower(): x.strip() for x in r.get("required_skills", [])}.values():
            key = s.lower()
            casing.setdefault(key, s)
            counts[casing[key]] = counts.get(casing[key], 0) + 1
    return (pd.Series(counts) / len(records) * 100).sort_values(ascending=False)


def dataset_size() -> int:
    return len(json.loads(CACHE_FILE.read_text())) if CACHE_FILE.exists() else 0


def match_skills(required: list[str], my_skills: list[str]) -> pd.DataFrame:
    mine = {s.lower() for s in my_skills}
    market = market_skill_pct()
    lookup = {k.lower(): v for k, v in market.items()}
    return pd.DataFrame({
        "Skill": required,
        "You have it": ["✅" if s.lower() in mine else "❌" for s in required],
        "% of sample postings requiring it": [f"{lookup.get(s.lower(), 0):.0f}%" for s in required],
    })


def dataset_records() -> list[dict]:
    return json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else []


def rank_postings(records: list[dict], my_skills: list[str]) -> pd.DataFrame:
    """Match the candidate's skills against every posting's required skills (no API calls)."""
    mine = {s.lower() for s in my_skills}
    rows = []
    for r in records:
        req = list(dict.fromkeys(s.strip() for s in r.get("required_skills", []) if s.strip()))
        have = [s for s in req if s.lower() in mine]
        missing = [s for s in req if s.lower() not in mine]
        rows.append({"company": r.get("company", ""), "job_title": r.get("job_title", ""),
                     "seniority": r.get("seniority", ""), "matched": len(have), "required": len(req),
                     "match_pct": round(100 * len(have) / len(req)) if req else None,
                     "missing": ", ".join(missing), "file": r.get("file", "")})
    df = pd.DataFrame(rows)
    return df.sort_values(["match_pct", "matched"], ascending=False, na_position="last").reset_index(drop=True) if len(df) else df


def missing_skill_summary(records: list[dict], my_skills: list[str]) -> pd.DataFrame:
    """Skills the candidate lacks, with the share of postings that require each one."""
    pct = market_skill_pct()
    mine = {s.lower() for s in my_skills}
    out = pd.DataFrame({"skill": pct.index, "pct": pct.values})
    return out[~out["skill"].str.lower().isin(mine)].reset_index(drop=True)


def save_to_dataset(text: str, posting: JobPosting, url: str = "") -> str:
    """Add the posting to postings/, sources.csv and the extraction cache."""
    POSTINGS_DIR.mkdir(exist_ok=True)
    for f in POSTINGS_DIR.glob("*.txt"):
        if f.read_text().strip() == text.strip():
            return f"Already in the dataset as {f.name}."
    nums = [int(f.stem.split("_")[-1]) for f in POSTINGS_DIR.glob("posting_*.txt")
            if f.stem.split("_")[-1].isdigit()]
    fname = f"posting_{max(nums, default=0) + 1:02d}.txt"
    (POSTINGS_DIR / fname).write_text(text.strip() + "\n")

    row = pd.DataFrame([[fname, posting.job_title, posting.company, "full posting (user added)", url or "not provided"]],
                       columns=["file", "job_title", "company", "text_completeness", "source_url"])
    if SOURCES_FILE.exists():
        row = pd.concat([pd.read_csv(SOURCES_FILE), row], ignore_index=True)
    row.to_csv(SOURCES_FILE, index=False)

    CACHE_FILE.parent.mkdir(exist_ok=True)
    cached = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else []
    cached.append({**posting.model_dump(), "file": fname})
    CACHE_FILE.write_text(json.dumps(cached, indent=2))
    return f"Saved as {fname}. Re-run the notebook from section 5 to include it in the charts."
