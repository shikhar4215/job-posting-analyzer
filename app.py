"""Job Posting Analyzer: web app.

Run from the project folder:
    uv run streamlit run app.py
"""
import hashlib

import streamlit as st

import core
import reports

st.set_page_config(page_title="Job Posting Analyzer", page_icon="📊", layout="wide")

DEFAULT_SKILLS = ["SQL", "Python", "Excel", "Tableau", "Statistics"]
COMMON_SKILLS = ["SQL", "Python", "R", "Excel", "Google Sheets", "Tableau", "Power BI", "Looker",
                 "Snowflake", "dbt", "BigQuery", "Redshift", "Databricks", "Statistics",
                 "A/B Testing", "Machine Learning", "Git", "AWS", "Data Modeling"]

market = core.market_skill_pct()


def show_api_error(e: Exception, model: str, action: str = "Analyze") -> None:
    msg = str(e)
    if "404" in msg and "model" in msg.lower():
        st.error(f"Gemini doesn't recognize the model '{model}'. Change it under Settings in the sidebar.\n\n{msg[:400]}")
    elif "API key" in msg or "401" in msg or "403" in msg or "GEMINI_API_KEY" in msg:
        st.error(f"There's a problem with your API key. Check the .env file.\n\n{msg[:400]}")
    elif "429" in msg:
        st.error("Rate limit reached. Wait a minute and try again.")
    elif "503" in msg or "UNAVAILABLE" in msg or "500" in msg:
        st.warning("Gemini is overloaded right now. The app retried several times without success. "
                   f"Wait a minute and click {action} again, or try a different model under Settings in the sidebar.")
    else:
        st.error(f"Something went wrong: {msg[:500]}")


# ---------------------------------------------------------------- sidebar: profile
with st.sidebar:
    st.header("Your profile")
    with st.expander("Settings"):
        model = st.text_input("Gemini model", value=core.DEFAULT_MODEL,
                              help="Change this if Google returns a 404 for the model name.")

    # Resume: parsed once per file and kept in session_state
    resume_file = st.file_uploader("Your resume (optional)", type=["pdf", "docx", "txt", "md"],
                                   help="Your skills, experience and education are read from it. "
                                        "The file stays on your computer; only its text is sent to Gemini.")
    if resume_file is None:
        st.session_state.pop("resume", None)
    else:
        data = resume_file.getvalue()
        digest = hashlib.md5(data).hexdigest()
        if st.session_state.get("resume", {}).get("hash") != digest:
            try:
                text = core.read_posting_file(resume_file.name, data)
                if len(text) < 100:
                    st.warning("Very little text came out of this resume. If it's a scanned PDF, upload a .docx or .txt instead.")
                with st.spinner("Reading your resume..."):
                    profile = core.extract_resume(core.get_client(), model, text)
                st.session_state["resume"] = {"hash": digest, "text": text, "profile": profile}
            except Exception as e:
                st.session_state.pop("resume", None)
                show_api_error(e, model, action="re-upload")

    resume = st.session_state.get("resume")
    resume_skills: list[str] = []
    if resume:
        p = resume["profile"]
        resume_skills = p.skills
        yrs = f"{p.years_experience:g} yrs experience · " if p.years_experience is not None else ""
        st.success(f"Resume read: {yrs}{len(p.skills)} skills found")
        use_resume = st.checkbox("Use skills from my resume", value=True)
        if not use_resume:
            resume_skills = []
        with st.expander("What Gemini found in your resume"):
            st.markdown("**Skills:** " + (", ".join(p.skills) or "none found"))
            if p.education:
                st.markdown("**Education:** " + "; ".join(p.education))
            st.markdown(p.experience_summary)

    options = list(dict.fromkeys(COMMON_SKILLS + list(market.index) + resume_skills))
    picked = st.multiselect("Other skills you have", options,
                            default=[] if resume_skills else [s for s in DEFAULT_SKILLS if s in options],
                            help="Add skills that aren't on your resume (or all your skills if you didn't upload one).")
    extra = st.text_input("More skills (comma separated)", placeholder="e.g. Alteryx, SAS")
    my_skills = list(dict.fromkeys(resume_skills + picked + [s.strip() for s in extra.split(",") if s.strip()]))
    st.caption(f"**Skills used for matching ({len(my_skills)}):** " + (", ".join(my_skills) or "none yet"))

    background = st.text_area(
        "Background (optional)",
        placeholder="e.g. 2 years in technical support, Master's in Data Science (in progress), built a SQL sales analysis project",
        height=120,
        help="Used for the recommendations. If you uploaded a resume, this is added to it.")
    if resume and not background.strip():
        p = resume["profile"]
        background = p.experience_summary + (" Education: " + "; ".join(p.education) if p.education else "")

    st.divider()
    if len(market):
        st.caption(f"Comparing against {core.dataset_size()} postings in data/extracted.json.")
    else:
        st.caption("No dataset results yet. Run the notebook once to enable the market comparison.")

resume_text = resume["text"] if resume else ""

# ---------------------------------------------------------------- page
st.title("📊 Job Posting Analyzer")
tab_one = st.container()

# ================================================================ TAB 1: single posting
with tab_one:
    st.write("Upload a job posting or paste its text, and Gemini will compare it with your profile and suggest what to do next.")

    src_upload, src_paste = st.tabs(["Upload a file", "Paste text"])
    with src_upload:
        uploaded = st.file_uploader("Job posting file", type=["pdf", "docx", "txt", "md"],
                                    help="PDF, Word (.docx), or plain text")
    with src_paste:
        pasted = st.text_area("Job posting text", height=260, placeholder="Paste the full job posting here...")
    url = st.text_input("Job URL (optional)", placeholder="https://...")

    posting_text = ""
    if uploaded is not None:
        try:
            posting_text = core.read_posting_file(uploaded.name, uploaded.getvalue())
            st.caption(f"Read {len(posting_text):,} characters from {uploaded.name}.")
            if len(posting_text) < 100:
                st.warning("Very little text came out of this file. If it's a scanned PDF, paste the text instead.")
        except Exception as e:
            st.error(f"Couldn't read the file: {e}")
    elif pasted.strip():
        posting_text = pasted.strip()

    if resume:
        st.caption("✓ Your resume will be used for the comparison and resume tips.")
    analyze = st.button("Analyze posting", type="primary", disabled=not posting_text)

    if analyze:
        try:
            client = core.get_client()
            with st.spinner("Reading the posting (retries automatically if Gemini is busy)..."):
                posting = core.extract_posting(client, model, posting_text)
            with st.spinner("Writing recommendations..."):
                recs = core.recommend(client, model, posting, my_skills, background, market, resume_text)
            st.session_state["result"] = {"text": posting_text, "posting": posting, "recs": recs,
                                          "skills": list(my_skills), "url": url, "saved_msg": None}
            st.session_state.pop("report", None)   # a new analysis makes any earlier report stale
        except Exception as e:
            show_api_error(e, model)

    res = st.session_state.get("result")
    if res:
        posting, recs = res["posting"], res["recs"]
        table = core.match_skills(posting.required_skills, res["skills"])
        have = int((table["You have it"] == "✅").sum())

        st.divider()
        st.header(f"{posting.job_title} · {posting.company}")

        pay = "Not listed"
        if posting.salary_min or posting.salary_max:
            unit = "/hr" if posting.pay_period == "hour" else "/yr"
            lo, hi = posting.salary_min, posting.salary_max
            pay = f"${lo:,.0f}–${hi:,.0f}{unit}" if lo and hi else f"${(lo or hi):,.0f}{unit}"
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Fit score (AI estimate)", f"{recs.fit_score}/100")
        c2.metric("Required skills you have", f"{have}/{len(table)}" if len(table) else "n/a")
        c3.metric("Seniority", posting.seniority.title())
        c4.metric("Min. experience", f"{posting.min_years_experience} yrs" if posting.min_years_experience is not None else "Not stated")
        c5.metric("Pay", pay)
        st.caption(f"Work mode: {posting.work_mode}")

        verdict_box = {"Strong": st.success, "Good": st.info, "Stretch": st.warning}[recs.verdict.split()[0]]
        verdict_box(f"**{recs.verdict}**. {recs.fit_summary}")

        left, right = st.columns([3, 2])
        with left:
            st.subheader("Required skills")
            if len(table):
                st.dataframe(table, hide_index=True, width="stretch")
            else:
                st.write("No required skills were found in this posting.")
            if posting.nice_to_have_skills:
                st.markdown("**Nice to have:** " + ", ".join(posting.nice_to_have_skills))
        with right:
            st.subheader("Your strengths")
            for s in recs.strengths:
                st.markdown(f"- {s}")

        st.subheader("Gaps to close")
        if recs.gaps:
            order = {"high": 0, "medium": 1, "low": 2}
            icon = {"high": "🔴", "medium": "🟠", "low": "⚪"}
            for g in sorted(recs.gaps, key=lambda g: order[g.priority]):
                with st.expander(f"{icon[g.priority]} {g.skill} ({g.priority} priority)", expanded=g.priority == "high"):
                    st.markdown(f"**Why it matters:** {g.why_it_matters}")
                    st.markdown(f"**How to close it:** {g.how_to_close}")
        else:
            st.write("No significant gaps found.")

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Resume tips")
            for t in recs.resume_tips:
                st.markdown(f"- {t}")
        with col_b:
            st.subheader("Interview prep")
            for t in recs.interview_topics:
                st.markdown(f"- {t}")

        # ------------------------------------------------------------ report section
        st.divider()
        st.header("📑 Report")
        st.write("Turn this analysis into a report. Choose the format and the sections to include, then generate it.")

        opt_left, opt_right = st.columns([2, 3])
        with opt_left:
            fmt = st.radio("Report format", list(reports.FORMATS), captions=list(reports.FORMATS.values()))
        with opt_right:
            chosen = st.multiselect("Sections to include", reports.SECTIONS, default=reports.SECTIONS,
                                    help="The same selection applies to every format.")
            sections = [s for s in reports.SECTIONS if s in chosen]   # keep the standard order
            engine, voice, rate = None, None, 185
            if fmt.startswith("Audio"):
                engines = reports.tts_engines()
                if engines:
                    engine = st.selectbox("Voice engine", engines)
                    if engine.startswith("macOS"):
                        voices = reports.mac_voices()
                        if voices:
                            voice = st.selectbox("Voice", voices,
                                                 index=voices.index("Samantha") if "Samantha" in voices else 0)
                        rate = st.slider("Speaking speed (words per minute)", 140, 240, 185, step=5)
                else:
                    st.warning("No text-to-speech engine found. Run `uv sync` to install one, then restart the app.")
            if fmt.startswith("Charts"):
                st.caption("Charts always show skill coverage and market demand; the section list doesn't affect them.")

        can_generate = bool(sections) and not (fmt.startswith("Audio") and engine is None)
        if not sections:
            st.info("Pick at least one section to include.")
        if st.button("Generate report", type="primary", disabled=not can_generate):
            stem = reports.file_stem(posting)
            try:
                with st.spinner(f"Building the {fmt} report..."):
                    rpt = {"fmt": fmt, "files": [], "preview_md": None, "script": None, "images": []}
                    if fmt == "PDF":
                        rpt["files"] = [(f"{stem}.pdf", reports.to_pdf(posting, recs, table, sections, market, res["skills"]),
                                         "application/pdf")]
                    elif fmt.startswith("Word"):
                        rpt["files"] = [(f"{stem}.docx", reports.to_docx(posting, recs, table, sections, market, res["skills"]),
                                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document")]
                    elif fmt == "Markdown":
                        md = reports.to_markdown(posting, recs, table, sections)
                        rpt["files"], rpt["preview_md"] = [(f"{stem}.md", md, "text/markdown")], md
                    elif fmt.startswith("Audio"):
                        script = reports.speech_script(posting, recs, table, sections)
                        audio, mime, ext = reports.to_audio(script, engine, voice, rate)
                        rpt["files"], rpt["script"] = [(f"{stem}.{ext}", audio, mime)], script
                    else:
                        pngs = reports.chart_pngs(posting, res["skills"], market)
                        rpt["files"] = [(f"{stem}_{name}", png, "image/png") for name, png in pngs.items()]
                        rpt["images"] = list(pngs.values())
                st.session_state["report"] = rpt
            except Exception as e:
                st.session_state.pop("report", None)
                st.error(f"Couldn't build the {fmt} report: {str(e)[:300]}")

        rpt = st.session_state.get("report")
        if rpt and rpt["fmt"] == fmt:   # only show a report that matches the selected format
            st.success(f"{rpt['fmt']} report ready.")
            if rpt["fmt"].startswith("Audio"):
                name, audio, mime = rpt["files"][0]
                st.audio(audio, format=mime)
                with st.expander("Read the spoken script"):
                    st.write(rpt["script"])
            for img in rpt["images"]:
                st.image(img, width=720)
            if rpt["preview_md"]:
                with st.expander("Preview", expanded=True):
                    st.markdown(rpt["preview_md"])
            for name, data, mime in rpt["files"]:
                st.download_button(f"⬇️ Download {name}", data, file_name=name, mime=mime, key=f"dl_{name}")

        st.divider()
        if st.button("💾 Save posting to dataset", help="Adds it to postings/, sources.csv and the notebook's cache"):
            res["saved_msg"] = core.save_to_dataset(res["text"], posting, res["url"])
        if res["saved_msg"]:
            st.success(res["saved_msg"])
