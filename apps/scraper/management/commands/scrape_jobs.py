from django.core.management.base import BaseCommand
from apps.scraper.scrapers.jobspy_scraper import scrape_linkedin, scrape_indeed
from apps.scraper.scrapers.pnet import scrape_pnet
from apps.scraper.scrapers.careerjunction import scrape_careerjunction
from apps.scraper.scrapers.careerjunction_it import scrape_careerjunction_it
from apps.scraper.scrapers.careers24 import scrape_careers24
from apps.scraper.scrapers.jobmail import scrape_jobmail
from apps.scraper.scrapers.gumtree import scrape_gumtree
from apps.scraper.scrapers.govjobs import scrape_dpsa, scrape_sayouth, scrape_essa, scrape_govza
from apps.scraper.models import Job
from apps.cv.models import CV

SCRAPERS = [
    ("PNet",              scrape_pnet,              "high"),
    ("CareerJunction",    scrape_careerjunction,    "high"),
    ("CareerJunction-IT", scrape_careerjunction_it, "high"),
    ("Careers24",         scrape_careers24,         "high"),
    ("JobMail",           scrape_jobmail,           "high"),
    ("DPSA",              scrape_dpsa,              "high"),
    ("SAYouth",           scrape_sayouth,           "medium"),
    ("ESSA",              scrape_essa,              "medium"),
    ("GovZA",             scrape_govza,             "medium"),
    ("Gumtree",           scrape_gumtree,           "medium"),
    ("LinkedIn",          scrape_linkedin,          "low"),
    ("Indeed",            scrape_indeed,            "low"),
]


class Command(BaseCommand):
    help = "Scrape jobs from all platforms"

    def add_arguments(self, parser):
        parser.add_argument("--keywords", type=str, default=None)
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--email-only", action="store_true")
        parser.add_argument("--gov-only", action="store_true", help="Only scrape government job platforms")
        parser.add_argument("--it-only", action="store_true", help="Only scrape IT-focused platforms")

    def handle(self, *args, **options):
        cv = CV.objects.filter(active=True).last()
        if not cv:
            self.stderr.write("No active CV. Upload one first via /upload-cv/")
            return

        keywords = options.get("keywords")
        if not keywords:
            skills = cv.parsed_data.get("skills", [])
            keywords = " ".join(skills[:3]) if skills else "developer"

        limit = options["limit"]
        email_only = options["email_only"]
        gov_only = options["gov_only"]
        it_only = options["it_only"]

        self.stdout.write(f"Searching: '{keywords}' | limit={limit}")

        gov_platforms = {"DPSA", "SAYouth", "ESSA", "GovZA"}
        it_platforms = {"PNet", "CareerJunction", "CareerJunction-IT", "LinkedIn", "Indeed"}

        scrapers = SCRAPERS
        if gov_only:
            scrapers = [s for s in SCRAPERS if s[0] in gov_platforms]
        elif it_only:
            scrapers = [s for s in SCRAPERS if s[0] in it_platforms]
        elif email_only:
            scrapers = [s for s in SCRAPERS if s[2] == "high"]

        all_jobs = []
        for name, fn, tier in scrapers:
            try:
                self.stdout.write(f"  [{tier.upper()}] {name}...", ending="")
                results = fn(keywords, limit=limit)
                count = len(results)
                email_count = sum(1 for j in results if j.get("apply_email"))
                self.stdout.write(f" {count} jobs, {email_count} with email")
                all_jobs += results
            except Exception as e:
                self.stdout.write(self.style.ERROR(f" failed: {e}"))

        created = skipped = 0
        for j in all_jobs:
            if not j.get("title"):
                continue
            _, new = Job.objects.get_or_create(
                title=j["title"],
                company=j.get("company", ""),
                platform=j["platform"],
                defaults={
                    "location": j.get("location", ""),
                    "description": j.get("description", ""),
                    "url": j.get("url", ""),
                    "apply_email": j.get("apply_email", ""),
                },
            )
            if new:
                created += 1
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {created} new jobs saved, {skipped} already existed."
        ))
