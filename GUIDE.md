# Job Posting Analyzer: Step-by-Step Guide

A practical guide to setting up, running, and extending the project on a Mac.

---

## 1. One-time setup

### Install uv
```bash
brew install uv
```

### Put the project in the right place
When you open a `.zip` on a Mac, it gets extracted into **Downloads**. Move the project folder to where you keep your coursework:

```bash
mv ~/Downloads/job-analyzer ~/Desktop/CU_StudyMaterial/CU_SEM4/AI_APPLICATIONS/Residency/
cd ~/Desktop/CU_StudyMaterial/CU_SEM4/AI_APPLICATIONS/Residency/job-analyzer
ls
```

`ls` should show `job_analyzer.ipynb`, `postings`, and `pyproject.toml`. If it doesn't, you're in the wrong folder.

### Install the dependencies
```bash
uv sync
```

### Add your Gemini API key
1. Create a key at https://aistudio.google.com/apikey
2. In the project folder, run:
   ```bash
   nano .env
   ```
3. Type one line: `GEMINI_API_KEY=` followed by your key (no spaces, no quotes).
4. Save: **Control + O**, then **Enter**. Exit: **Control + X**. (Use the Control key, not Command.)

Never paste your key into chats, screenshots, or the notebook itself. `.env` is listed in `.gitignore`, so git won't commit it.

---

## 2. Running the notebook

```bash
uv run jupyter lab
```

This Terminal tab now belongs to Jupyter and won't accept other commands. **Open a second tab (Command + T)** for anything else.

In JupyterLab:
1. Open `job_analyzer.ipynb` from the left sidebar.
2. Run cells top to bottom with **Shift + Enter**, or use **Run → Run All Cells**.
3. After changing `.env` or restarting, use **Kernel → Restart Kernel** and run everything again from the top.

| Section | What it does |
|---|---|
| 1. Setup | Loads the API key and creates the Gemini client |
| 2. Schema | Defines the `JobPosting` fields the model must return |
| 3. Extraction | The prompt and the function that calls Gemini |
| 4. Test one | Extracts a single posting so you can check it |
| 5. Run all | Extracts every posting and caches the results in `data/extracted.json` |
| 6. Analysis | Skill frequency, required vs. nice-to-have, seniority, work mode, salary |
| 7. Skill gap | Compares `MY_SKILLS` with what employers require |
| 8. Your own posting | Paste any posting, analyze it, and optionally save it to the dataset |
| 9. Validation | Shows random postings next to the model's output for manual checking |
| 10. Findings | Your write-up and the limitations section |

Charts are saved to the `figures/` folder.

---

## 3. Using the web app

The web app is the easiest way to analyze a single posting and get recommendations.

```bash
uv run streamlit run app.py
```

Your browser opens at `http://localhost:8501`. (Like Jupyter, this occupies the Terminal tab. Stop it with **Control + C**.)

1. **Sidebar: upload your resume** (PDF, .docx or .txt). Gemini reads your skills, years of experience and education once. Open **What Gemini found in your resume** to check them. Add anything it missed under **Other skills** or **More skills**, and uncheck **Use skills from my resume** if you'd rather enter skills by hand.
2. **Add the posting:** upload a posting file (PDF, .docx, .txt) or switch to **Paste text**.
3. Click **Analyze posting**. Gemini makes two calls: one extracts the posting, the other writes recommendations.
4. Review the verdict, the skill table, the gaps (high priority first), resume tips and interview prep.
5. Scroll to **Report** to export the analysis (details below). **Save posting to dataset** adds the posting to the notebook's data.

### Generating a report

1. **Pick a format:** PDF, Word (.docx), Markdown, Audio (text-to-speech) or Charts (PNG).
2. **Pick the sections** to include. All seven are selected by default; remove any you don't want. The same selection applies to every format.
3. Click **Generate report**. A preview appears where the format allows it (the audio player, the charts, the Markdown text), with a download button below.
4. To get another format, select it and click **Generate report** again.

| Format | Notes |
|---|---|
| PDF | Best for printing or submitting. Includes the charts when the Charts section is selected. |
| Word (.docx) | Same content, editable. |
| Markdown | Text only; charts are left out. |
| Audio | On a Mac it uses the built-in system voice (offline); you can choose the voice and speaking speed. Otherwise it uses Google's online text-to-speech, which needs an internet connection. Open **Read the spoken script** to see the text. |
| Charts (PNG) | Skill coverage (how many required and nice-to-have skills you have) and market demand (how common each skill is in the dataset). The demand chart needs `data/extracted.json` from the notebook. |

Your resume file stays on your computer. Only its text is sent to Gemini, and nothing is saved to disk.

Scanned PDFs (images of text) can't be read. Paste the text instead.

Run the notebook once before using the app. The "% of sample postings" column comes from `data/extracted.json`, which the notebook creates.

---

## 4. Adding your own job posting (notebook)

### Option A: paste it into the notebook (easiest)
Section 8 has a text box.
1. Run sections 1–7 first (or **Run → Run All Cells**).
2. Paste the full posting into the box. Optionally add the job URL in the field below it.
3. Click **Analyze posting**. You'll see the extracted details, which required skills you have, what's missing, and how common each skill is across the dataset.
4. To keep it, click **Save to dataset**. The notebook saves it as the next `posting_NN.txt`, adds a row to `sources.csv`, and adds the result to the cache.
5. Re-run from section 5 down to update the charts. You don't need `REFRESH`, because the new posting is already in the cache.

Pasting the same posting twice is caught automatically; it won't be saved again.

If the text box doesn't appear, run `uv sync` in Terminal (it installs `ipywidgets`), then restart the kernel.

### Option B: add a file by hand
1. In the JupyterLab sidebar, open `postings`, right-click → **New File** → `posting_21.txt` (next unused number), paste the posting, and save with **Command + S**.
2. Add a row to `sources.csv`: `posting_21.txt,Data Analyst,Company Name,full posting,https://link-to-the-job`
3. In section 5, set `REFRESH = True` and run all cells, then set it back to `False`.

---

## 5. Customizing

| What | Where | How |
|---|---|---|
| Your skills | Section 7 | Edit the `MY_SKILLS` list, using the same names that appear in the charts |
| Model | Notebook section 1 / app sidebar | Change `MODEL` in the notebook, or use **Settings** in the app sidebar. Use a name Google currently offers, e.g. `gemini-3.8-flash` |
| Extraction rules | Section 3 | Edit `SYSTEM_PROMPT`, then set `REFRESH = True` |
| Skill name variants | Section 6.1 | Add entries to `ALIASES`, e.g. `"ms sql server": "SQL"` |
| Which postings get spot-checked | Section 9 | Change `SEED` |

---

## 6. Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `cd: no such file or directory` | The folder isn't where you think it is | Run `ls ~/Downloads \| grep job` to find it, then `mv` it (section 1) |
| `No pyproject.toml found` | You're running `uv` outside the project folder | `cd` into the project folder first |
| `GEMINI_API_KEY not found` | No `.env` file in the project folder | Create it with `nano .env` (section 1), then restart the kernel |
| `401` / invalid API key | `.env` holds a placeholder or a wrong key | Check with `!cut -c1-20 .env` in a cell, fix the key, restart the kernel |
| `429` / quota or rate-limit error | Too many requests, or no quota left | The notebook retries automatically; if it keeps failing, wait a minute or check your quota in AI Studio |
| Typing in Terminal does nothing | That tab is running Jupyter | Open a new tab with **Command + T** |
| Stuck in the `nano` editor | | **Control + X**, then **N** to quit without saving |
| Old results after changing the prompt | Results are cached | Set `REFRESH = True` in section 5 |
| Section 8 text box doesn't appear | `ipywidgets` isn't installed | Run `uv sync`, then **Kernel → Restart Kernel** |
| `404 NOT_FOUND` for the model | That model name isn't available for your key | Use the name suggested in the error message (e.g. `gemini-3.8-flash`) |
| `streamlit: command not found` | Dependencies not installed | Run `uv sync`, then `uv run streamlit run app.py` |
| Report: "No text-to-speech engine found" | Dependencies not installed | Run `uv sync`, then restart the app |
| Report: audio fails with Google TTS | No internet, or Google's service refused the request | On a Mac choose **macOS voice (offline)**; otherwise try again later |
| `.env.txt` instead of `.env` | TextEdit added `.txt` | Create the file with `nano` instead of TextEdit |

---

## 7. Before you submit

- [ ] `MY_SKILLS` reflects your real skills
- [ ] The section 9 spot-check table is filled in (errors found per posting)
- [ ] The section 10 findings are written from your actual charts
- [ ] Limitations mention the 14 partial postings (see `sources.csv`)
- [ ] `.env` is **not** included in anything you upload or share
