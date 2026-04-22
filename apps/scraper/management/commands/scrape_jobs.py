from django.core.management.base import BaseCommand
from concurrent.futures import ThreadPoolExecutor, as_completed
from apps.scraper.scrapers.jobspy_scraper import scrape_linkedin, scrape_indeed
from apps.scraper.scrapers.pnet import scrape_pnet
from apps.scraper.scrapers.careerjunction import scrape_careerjunction, scrape_careerjunction_it
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

GOV_PLATFORMS = {"DPSA", "SAYouth", "ESSA", "GovZA"}
IT_PLATFORMS  = {"PNet", "CareerJunction", "CareerJunction-IT", "LinkedIn", "Indeed"}


class Command(BaseCommand):
    help = "Scrape jobs from all platforms in parallel"

    def add_arguments(self, parser):
        parser.add_argument("--keywords", type=str, default=None)
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--email-only", action="store_true")
        parser.add_argument("--gov-only", action="store_true")
        parser.add_argument("--it-only", action="store_true")
        parser.add_argument("--workers", type=int, default=4,
                            help="Max parallel scrapers (default: 4)")

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
        workers = options["workers"]

        scrapers = SCRAPERS
        if options["gov_only"]:
            scrapers = [s for s in SCRAPERS if s[0] in GOV_PLATFORMS]
        elif options["it_only"]:
            scrapers = [s for s in SCRAPERS if s[0] in IT_PLATFORMS]
        elif options["email_only"]:
            scrapers = [s for s in SCRAPERS if s[2] == "high"]

        self.stdout.write(f"Searching: '{keywords}' | limit={limit} | scrapers={len(scrapers)} | workers={workers}\n")

        all_jobs = []

        def _run_scraper(name, fn, tier):
            try:
                results = fn(keywords, limit=limit)
                email_count = sum(1 for j in results if j.get("apply_email"))
                self.stdout.write(
                    f"  [{tier.upper()}] {name}: {len(results)} jobs, {email_count} with email"
                )
                return results
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  [{tier.upper()}] {name}: failed — {e}"))
                return []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run_scraper, name, fn, tier): name
                       for name, fn, tier in scrapers}
            for future in as_completed(futures):
                try:
                    all_jobs += future.result()
                except Exception:
                    pass

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
