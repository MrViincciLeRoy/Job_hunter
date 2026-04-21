# Job Hunter

Scrapes LinkedIn, Indeed, PNet, and CareerJunction. Matches jobs to your CV using Groq AI. Sends email applications automatically with a generated cover letter.

## Setup (Local)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your keys + DATABASE_URL
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Go to `http://127.0.0.1:8000/upload-cv/` and upload your PDF CV first.

## Deploy to Render + Neon

1. Create a free Postgres DB at [neon.tech](https://neon.tech) → copy the connection string
2. Push this repo to GitHub
3. Create a new **Web Service** on Render, connect your repo, then set:
   - **Build Command:** `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
   - **Start Command:** `gunicorn job_hunter.wsgi:application --bind 0.0.0.0:$PORT --workers 2`
4. Add env vars in Render dashboard:
   - `DATABASE_URL` → your Neon connection string
   - `GROQ_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `SECRET_KEY`

## Running

```bash
python run.py all          # scrape + match + apply
python run.py scrape
python run.py match
python run.py apply
python run.py apply --dry-run

python manage.py scrape_jobs --keywords "python developer" --limit 30
python manage.py apply_jobs --threshold 50
```

## How It Works

1. Upload CV → Groq parses it → extracts name, email, skills, experience
2. Scrape → pulls jobs from LinkedIn/Indeed (jobspy) + PNet/CareerJunction (custom)
3. Match → Groq scores each job 0–100 against your CV
4. Apply → sends email + cover letter + CV attachment to jobs scoring ≥60 with an email

## Notes

- Green dot = job has an email (will be applied to)
- Grey dot = no email found
- PNet and CareerJunction expose the most email addresses
- Admin panel at `/admin/`
