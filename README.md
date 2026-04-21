# Job Hunter

Scrapes LinkedIn, Indeed, PNet, and CareerJunction. Matches jobs to your CV using Groq AI. Sends email applications automatically with a generated cover letter.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your keys
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Go to `http://127.0.0.1:8000/upload-cv/` and upload your PDF CV first.

## Running

```bash
# All steps at once
python run.py all

# Or individually
python run.py scrape          # pull jobs from all platforms
python run.py match           # score jobs against your CV
python run.py apply           # send emails to matched jobs
python run.py apply --dry-run # preview without sending

# Override keywords
python manage.py scrape_jobs --keywords "python developer" --limit 30

# Lower the match threshold (default 60)
python manage.py apply_jobs --threshold 50
```

## How It Works

1. Upload CV → Groq parses it and extracts name, email, skills, experience
2. Scrape → pulls jobs from LinkedIn/Indeed (via jobspy) + PNet/CareerJunction (custom scrapers)
3. Match → Groq scores each job 0–100 against your CV
4. Apply → sends email with AI-written cover letter + CV attached to any job scoring ≥60 that has an email

## Notes

- Green dot on dashboard = job has an email address (will be applied to)
- Grey dot = no email found (visible in dashboard but won't be emailed)
- PNet and CareerJunction are the best sources for exposed email addresses
- LinkedIn/Indeed jobs are still scored and tracked but rarely expose emails
- Admin panel at `/admin/` to view/manage everything
