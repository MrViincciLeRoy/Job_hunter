# 🎯 Job Hunter

Automated job discovery, AI-powered matching, and email application system.

[![Deployment Status](https://img.shields.io/badge/Deploy-Render-blue?style=flat-square)](https://render.com)
[![Engine](https://img.shields.io/badge/AI-Groq-green?style=flat-square)](https://groq.com)

## 🚀 Key Features

-   **Multi-Source Scraper**: Aggregates listings from LinkedIn, Indeed, PNet, CareerJunction, DPSA, and more.
-   **AI Matching**: Uses Groq LLM to score jobs (0–100) based on your parsed CV.
-   **Auto-Applier**: Automatically generates tailored cover letters and emails your CV to jobs meeting your threshold.
-   **Termux Compatible**: Full support for running as a background bot on Android via Termux.
-   **Dashboard**: Clean UI to manage your profile, documents, and tracked job applications.

## 🛠️ Quick Start

### Local Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env  # Update with your API keys & DATABASE_URL

# Database setup
python manage.py migrate
python manage.py createsuperuser

# Start server
python manage.py runserver
```

### Termux Installation
```bash
pkg install python git nodejs-lts
git clone https://github.com/MrViincciLeRoy/Job_hunter.git
cd Job_hunter
pip install -r requirements-termux.txt
# Follow local setup steps above
```

## 🤖 Operation

Use the unified runner to control the pipeline:

| Command | Action |
| :--- | :--- |
| `python run.py scrape` | Fetch new jobs from all platforms |
| `python run.py match` | Run AI scoring against your CV |
| `python run.py apply` | Send applications (Emails/CVs) |
| `python run.py all` | Run the full pipeline sequentially |
| `python run.py apply --dry-run` | Preview applications without sending |

## 🏗️ Technical Architecture

1.  **CV Parsing**: Uploaded PDFs are parsed via LLM into structured data (Skills, Experience, Education).
2.  **Scraping**: `jobspy` handles major boards; custom scrapers (`utils/scraper_utils.py`) target niche sites and extract HR emails.
3.  **Matching**: `matcher_algo.py` feeds job descriptions and CV data to Groq to determine fit.
4.  **Mailing**: `apps.mailer` manages Gmail API integration for high-deliverability applications.

## ☁️ Deployment

Designed for easy deployment on **Render** using **Neon Postgres**:
-   **Build:** `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
-   **Start:** `gunicorn job_hunter.wsgi:application`
-   **Env Vars Required:** `DATABASE_URL`, `GROQ_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `SECRET_KEY`.

---
*Developed for the modern job seeker.*
