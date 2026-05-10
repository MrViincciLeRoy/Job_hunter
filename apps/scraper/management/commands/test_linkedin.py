from django.core.management.base import BaseCommand
from apps.scraper.scrapers.linkedin import scrape_linkedin


class Command(BaseCommand):
    help = "Test the LinkedIn scraper and print results"

    def add_arguments(self, parser):
        parser.add_argument("--keywords", type=str, default="python developer south africa")
        parser.add_argument("--limit",    type=int, default=10)

    def handle(self, *args, **options):
        keywords = options["keywords"]
        limit    = options["limit"]

        self.stdout.write(f"\nLinkedIn scraper test")
        self.stdout.write(f"Keywords : {keywords}")
        self.stdout.write(f"Limit    : {limit}")
        self.stdout.write("─" * 60)

        try:
            jobs = scrape_linkedin(keywords=keywords, limit=limit)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Scraper raised: {e}"))
            import traceback
            traceback.print_exc()
            return

        if not jobs:
            self.stdout.write(self.style.WARNING("\nNo jobs returned. Possible causes:"))
            self.stdout.write("  • LINKEDIN_EMAIL / LINKEDIN_PASSWORD not set")
            self.stdout.write("  • Chrome / chromedriver not installed")
            self.stdout.write("  • LinkedIn blocked the session")
            return

        self.stdout.write(self.style.SUCCESS(f"\n{len(jobs)} job(s) returned:\n"))

        for i, job in enumerate(jobs, 1):
            self.stdout.write(f"[{i}] {job.get('title', '—')}")
            self.stdout.write(f"    Company  : {job.get('company', '—')}")
            self.stdout.write(f"    Location : {job.get('location', '—')}")
            self.stdout.write(f"    Type     : {job.get('job_type', '—')}")
            self.stdout.write(f"    Salary   : {job.get('salary', '—')}")
            self.stdout.write(f"    Email    : {job.get('apply_email', '—')}")
            self.stdout.write(f"    Closing  : {job.get('closing_date', '—')}")
            self.stdout.write(f"    URL      : {job.get('url', '—')}")
            desc = (job.get('description') or '').replace('\n', ' ')
            self.stdout.write(f"    Desc     : {desc[:120]}{'...' if len(desc) > 120 else ''}")
            self.stdout.write("")

        # Summary
        with_email   = sum(1 for j in jobs if j.get('apply_email'))
        with_salary  = sum(1 for j in jobs if j.get('salary'))
        with_closing = sum(1 for j in jobs if j.get('closing_date'))

        self.stdout.write("─" * 60)
        self.stdout.write(f"  Total returned : {len(jobs)}")
        self.stdout.write(f"  With email     : {with_email}")
        self.stdout.write(f"  With salary    : {with_salary}")
        self.stdout.write(f"  With closing   : {with_closing}")
        self.stdout.write("─" * 60 + "\n")
