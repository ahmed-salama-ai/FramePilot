# FramePilot – Smart Multi-Camera Editing

FramePilot is a web application that automates multi-camera video editing using AI. Upload raw footage from 2–4 camera angles, and the system will synchronize the recordings, detect the active speaker, generate captions, extract highlights, and produce a final edited video.

## Features

- **Multi-Camera Upload** – Upload 2 to 4 camera videos at once with a drag-and-drop interface.
- **AI-Powered Editing Pipeline** – Automated stages: Ingest & Sync, Audio & Captions, Perception, AI Brain, Camera Switching, Rendering, Highlights, and Evaluation.
- **Interactive Results Dashboard** – View the final video with an interactive camera-switching confidence chart (Chart.js).
- **Auto-Generated Captions** – Arabic and English SRT subtitles, downloadable from the results page.
- **Highlight Extraction** – AI-curated short-form clips in both 16:9 and 9:16 aspect ratios.
- **AI Chat Assistant** – Ask natural language questions about your video content and request specific clip extractions.
- **Labelling Tool** – Manual camera-switching annotation tool with keyboard shortcuts (press 1–4 to switch cameras, H for highlights).
- **Dark Mode** – Toggle between light and dark themes; preference is saved in localStorage.
- **Responsive UI** – Built with PicoCSS + custom CSS for a clean, modern SaaS look.

## Tech Stack

| Layer | Technology |
| ------- | ----------- |
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Database | SQLite (via `app/db.py`) |
| Frontend | Jinja2 Templates, PicoCSS, Chart.js |
| Worker | Background job processor (`app/worker.py`) |

## Project Structure

` ` `
FramePilot/
├── app/
│   ├── main.py            # FastAPI routes and API endpoints
│   ├── db.py              # SQLite database wrapper
│   ├── worker.py          # Background pipeline worker
│   ├── static/
│   │   ├── style.css      # Custom theme (light/dark mode, layout)
│   │   └── app.js         # Upload progress bar (XHR)
│   └── templates/
│       ├── base.html      # Base layout (navbar, dark mode toggle, footer)
│       ├── index.html     # Home page (upload form, recent projects)
│       ├── job.html       # Processing progress page (live polling)
│       ├── results.html   # Results dashboard (video, chart, chat, highlights)
│       └── label.html     # Manual labelling tool
├── data/                  # Runtime data (created automatically, git-ignored)
│   ├── app.db             # SQLite database
│   └── sessions/          # Uploaded videos and generated outputs
├── avatar/static/         # 3D host avatar assets (optional)
├── requirements.txt       # Python dependencies
├── .gitignore
└── README.md
` ` `

## Getting Started

### Prerequisites

- **Python 3.10+** installed
- **pip** or **uv** package manager

### 1. Clone the Repository

```bash
git clone https://github.com/<your-username>/FramePilot.git
cd FramePilot
```

### 2. Create a Virtual Environment

```bash
# Using uv (recommended)
uv venv --python 3.10
# Or using standard venv
python -m venv .venv
```

Activate the environment:

```bash
# Windows (PowerShell)
.\.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the Server

```bash
uvicorn app.main:app --reload
```

The app will be available at **<http://127.0.0.1:8000>**.

### 5. Run the Background Worker

Open a **second terminal** (with the virtual environment activated):

```bash
python -m app.worker
```

The worker monitors the `jobs` table and processes video uploads through the pipeline stages.

> **Note:** The worker currently runs in `FAKE = True` mode, which simulates the pipeline with dummy stages. Set `FAKE = False` in `app/worker.py` once the real AI pipeline (`ai_director.pipeline.run_pipeline`) is integrated.

## How to Use

1. Open **<http://127.0.0.1:8000>** in your browser.
2. Fill in the **Project Name**, select the **Language** and **Wide Shot Camera Index**.
3. Click the upload area and select **2 to 4 video files**.
4. Press **"Process Video Files"** – a progress bar will show each pipeline stage.
5. Once processing is complete, you will be redirected to the **Results Dashboard** where you can:
   - Watch the final edited video with embedded captions.
   - Download the edited video and SRT subtitle files.
   - View the **Camera Switching Analysis** chart (click to seek).
   - Browse **Extracted Highlights** and download them.
   - Chat with the **AI Video Assistant** to request specific clips.

## API Endpoints

| Method | Endpoint | Description |
| -------- | ---------- | ------------- |
| `GET` | `/` | Home page with upload form and recent projects |
| `POST` | `/api/projects` | Create a new project (multipart form with video files) |
| `GET` | `/api/jobs/{job_id}` | Get job status (JSON) |
| `GET` | `/jobs/{job_id}` | Job progress page (HTML) |
| `GET` | `/results/{sid}` | Results dashboard (HTML) |
| `GET` | `/label/{sid}` | Manual labelling tool (HTML) |
| `POST` | `/api/labels/{sid}` | Save manual labels |
| `POST` | `/api/agent/{sid}` | Send a message to the AI chat assistant |
| `POST` | `/api/projects/{sid}/delete` | Delete a project |

## Contributing

### For Team Members

1. **Fork** the repository or create a new **branch** from `main`:
   ` ` `bash
   git checkout -b feature/your-feature-name
   ` ` `

2. Make your changes following the existing code structure.

3. **Test locally** by running both the server and worker.

4. **Commit and push** your changes:
   ` ` ` bash
   git add .
   git commit -m "Add: brief description of your changes"
   git push origin feature/your-feature-name
   ` ` `

5. Open a **Pull Request** to `main` with a clear description of what you changed.

### Integration Points for Team Tasks

| Task | Where to Work | Notes |
| ------ | --------------- | ------- |
| **AI Pipeline Integration** | `app/worker.py` | Set `FAKE = False` and ensure `ai_director.pipeline.run_pipeline` is importable. The function receives `(session_dir, on_progress_callback)`. |
| **AI Chat Agent** | `app/main.py` → `agent_chat()` | Replace the dummy response with the real LangChain/RAG agent. It receives `(session_dir, message, history)` and should return `{"reply": str, "steps": list, "clips": list}`. |
| **Evaluation Metrics** | `app/templates/results.html` | Add a metrics card that reads from `data/sessions/{sid}/metrics.json`. The JSON should contain `{"wer": float, "agreement": float, ...}`. |
| **3D Avatar** | `avatar/static/` | Static files are served at `/avatar/`. The avatar page can be embedded via iframe or linked from results. |
| **CI/CD** | `.github/workflows/` | Add a `python.yml` workflow with `install`, `lint` (ruff/flake8), and `test` (pytest) steps. |

### Code Style

- Python: Follow PEP 8. Use type hints where possible.
- HTML/CSS: Use the existing CSS variables (`--primary-color`, `--card-bg`, etc.) for consistency.
- JavaScript: Use modern ES6+ syntax.

## License

This project is developed as part of the NTI program. See the team for licensing details.

---

Built with care by **Ahmed Sameh & Team**
