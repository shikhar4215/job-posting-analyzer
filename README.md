# Job Posting Analyzer

Uses the **Gemini API** to turn unstructured Data Analyst job postings into structured data (skills, seniority, work mode, experience, salary), then analyzes the results with pandas to show which skills employers ask for most.

## How it works

1. **Input:** 20 job postings as plain text in `postings/`. Their source links are in `sources.csv`.
2. **Extraction:** each posting goes to Gemini with a Pydantic schema (`JobPosting`). Gemini's structured output mode makes the reply match that schema, so no text parsing is needed.
3. **Caching:** results are saved to `data/extracted.json`, so the API is only called once.
4. **Analysis:** skill frequency, required vs. nice-to-have, seniority, work mode, experience, salary, and a personal skill-gap check. Charts are saved to `figures/`.
5. **Your own posting:** an interactive text box where you paste any posting, see your skill match, and optionally add it to the dataset.
6. **Validation:** a spot-check section compares the model's output against the original text.

## Web app

`app.py` is a browser interface built with Streamlit. Upload your resume once in the sidebar (optional), and Gemini reads your skills, experience and education. Then upload a job posting (PDF, Word or text) or paste it, and Gemini returns:

- a verdict and fit score
- which required skills you have, and how common each one is across the dataset
- prioritized skill gaps, each with a concrete way to close it
- resume tips and interview topics for that specific role

### Reports

After an analysis, the **Report** section turns the results into a report in the format you choose:

| Format | What you get |
|---|---|
| PDF | A formatted document with the summary, skills table, charts, gaps and tips |
| Word (.docx) | The same content as an editable document |
| Markdown | Plain text with formatting, with a preview in the app |
| Audio (text-to-speech) | A spoken summary you can play in the app or download |
| Charts (PNG) | Skill coverage and market demand graphs |

You also choose which sections to include (Summary, Skills table, Charts, Strengths, Gaps to close, Resume tips, Interview prep). The same selection applies to every format.

You can also save the posting into the dataset with one click.

```bash
uv run streamlit run app.py
```

## Setup (Mac)

1. Install uv if needed: `brew install uv`
2. In this folder, install the dependencies:
   ```bash
   uv sync
   ```
3. Get a Gemini API key from Google AI Studio (https://aistudio.google.com/apikey).
4. Create a file named `.env` in this folder containing one line:
   ```
   GEMINI_API_KEY=your-key-here
   ```
   `.env` is listed in `.gitignore`, so the key is never committed.
5. Start Jupyter and open `job_analyzer.ipynb`:
   ```bash
   uv run jupyter lab
   ```
6. Run the cells top to bottom (or use Run → Run All Cells).

## Project structure

```
job-analyzer/
├── job_analyzer.ipynb   # the full pipeline and analysis
├── app.py               # Streamlit web app (upload a posting, get recommendations)
├── core.py              # Gemini calls and file reading used by app.py
├── reports.py           # report generation: PDF, Word, Markdown, audio, charts
├── postings/            # 20 job postings (.txt)
├── sources.csv          # source link + completeness for each posting
├── data/                # extracted.json is written here
├── figures/             # charts are saved here
├── GUIDE.md             # step-by-step setup, usage and troubleshooting
├── pyproject.toml       # dependencies (managed by uv)
├── .env.example         # template for your API key
└── .gitignore
```

## Customizing

- **Model:** change `MODEL` in the notebook's setup cell. In the web app, use Settings in the sidebar, or add `GEMINI_MODEL=model-name` to `.env`.
- **Your skills:** edit `MY_SKILLS` in section 7.
- **Re-run extraction** after changing the prompt: set `REFRESH = True` in section 5.
- **Add postings:** paste them into the text box in section 8 and click **Save to dataset**, or drop `.txt` files into `postings/`, add a row for each in `sources.csv`, and set `REFRESH = True`.

## Data note

14 of the 20 postings were reconstructed from search-listing text because the original pages had closed. `text_completeness` in `sources.csv` marks which ones. All postings were collected in November 2026.
