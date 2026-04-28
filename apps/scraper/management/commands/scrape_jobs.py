"""
scrape_jobs — bulk scraper command, no artificial limits.

Usage:
  python manage.py scrape_jobs                        # uses CV skills as keywords, all pages
  python manage.py scrape_jobs --keywords "IT admin"  # specific search
  python manage.py scrape_jobs --max-jobs 500         # safety brake per scraper (default: unlimited)
  python manage.py scrape_jobs --max-pages 50         # max pages per scraper (default: unlimited)
  python manage.py scrape_jobs --gov-only             # gov platforms only
  python manage.py scrape_jobs --workers 6            # parallel scraper threads
  python manage.py scrape_jobs --scrapers pnet careerjunction  # specific scrapers only
"""

from django.core.management.base import BaseCommand
from concurrent.futures import ThreadPoolExecutor, as_completed
from apps.scraper.scrapers.pnet import scrape_pnet
from apps.scraper.scrapers.careerjunction import scrape_careerjunction, scrape_careerjunction_it
from apps.scraper.scrapers.careers24 import scrape_careers24
from apps.scraper.scrapers.jobmail import scrape_jobmail
from apps.scraper.scrapers.gumtree import scrape_gumtree
from apps.scraper.scrapers.govjobs import scrape_dpsa, scrape_sayouth, scrape_essa, scrape_govza
from apps.scraper.models import Job
from apps.cv.models import CV

# ─── Scraper registry ────────────────────────────────────────────────────────
# (name, fn, tier, slug)
# tier: "gov" | "high" | "medium" | "low"
SCRAPERS_PRIMARY = [
    ("DPSA",              scrape_dpsa,              "gov",    "dpsa"),
    ("SAYouth",           scrape_sayouth,           "gov",    "sayouth"),
    ("ESSA",              scrape_essa,              "gov",    "essa"),
    ("GovZA",             scrape_govza,             "gov",    "govza"),
    ("PNet",              scrape_pnet,              "high",   "pnet"),
    ("CareerJunction",    scrape_careerjunction,    "high",   "careerjunction"),
    ("CareerJunction-IT", scrape_careerjunction_it, "high",   "careerjunction_it"),
    ("Careers24",         scrape_careers24,         "high",   "careers24"),
    ("JobMail",           scrape_jobmail,           "high",   "jobmail"),
    ("Gumtree",           scrape_gumtree,           "medium", "gumtree"),
]

SCRAPERS_JOBSPY = []
try:
    from apps.scraper.scrapers.jobspy_scraper import scrape_linkedin, scrape_indeed
    SCRAPERS_JOBSPY = [
        ("LinkedIn", scrape_linkedin, "low", "linkedin"),
        ("Indeed",   scrape_indeed,   "low", "indeed"),
    ]
except ImportError:
    pass

GOV_PLATFORMS    = {"dpsa", "sayouth", "essa", "govza"}
IT_PLATFORMS     = {"pnet", "careerjunction", "careerjunction_it"}
GOV_PRIORITY_KW  = "internship learnership entry level graduate IT"

# How many pages each scraper supports when unlimited
# These are passed as `max_pages` kwargs — scrapers loop until exhausted
SCRAPER_MAX_PAGES = {
    "DPSA":              1,     # one PDF circular (or N circulars if enhanced)
    "SAYouth":           20,
    "ESSA":              20,
    "GovZA":             10,
    "PNet":              50,
    "CareerJunction":    50,
    "CareerJunction-IT": 50,
    "Careers24":         30,
    "JobMail":           30,
    "Gumtree":           20,
    "LinkedIn":          10,
    "Indeed":            10,
}


def _t(value, max_len):
    return (value or "")[:max_len]


class Command(BaseCommand):
    help = "Bulk-scrape jobs from SA/gov platforms — no artificial job limits"

    def add_arguments(self, parser):
        parser.add_argument("--keywords",       type=str,   default=None,
                            help="Search keywords (default: derived from active CV skills)")
        parser.add_argument("--max-jobs",       type=int,   default=0,
                            help="Max jobs to return per scraper (0 = unlimited, default: 0)")
        parser.add_argument("--max-pages",      type=int,   default=0,
                            help="Max pages per scraper (0 = use scraper defaults, default: 0)")
        parser.add_argument("--email-only",     action="store_true",
                            help="Only run high-yield email scrapers")
        parser.add_argument("--gov-only",       action="store_true",
                            help="Only run government scrapers")
        parser.add_argument("--it-only",        action="store_true",
                            help="Only run IT-focused scrapers")
        parser.add_argument("--include-jobspy", action="store_true",
                            help="Also run LinkedIn/Indeed via jobspy (low email yield)")
        parser.add_argument("--workers",        type=int,   default=4,
                            help="Parallel scraper threads (default: 4)")
        parser.add_argument("--scrapers",       nargs="*",  default=None,
                            help="Run specific scrapers by slug (e.g. pnet careerjunction dpsa)")
        parser.add_argument("--skip-existing",  action="store_true", default=True,
                            help="Skip URLs already in DB (default: True)")
        parser.add_argument("--no-skip",        action="store_true",
                            help="Disable skip-existing (re-scrape everything)")

    def handle(self, *args, **options):
        cv = CV.objects.filter(active=True).last()
        if not cv:
            self.stderr.write("No active CV. Upload one first via /upload-cv/")
            return

        # ── Keywords ──────────────────────────────────────────────────────────
        keywords = options.get("keywords")
        user_set_keywords = bool(keywords)
        if not keywords:
            skills = cv.parsed_data.get("skills", [])
            keywords = " ".join(skills[:4]) if skills else "developer"

        max_jobs     = options["max_jobs"]      # 0 = unlimited
        max_pages    = options["max_pages"]     # 0 = use SCRAPER_MAX_PAGES defaults
        workers      = options["workers"]
        skip_existing = not options.get("no_skip", False)

        # ── Build scraper list ────────────────────────────────────────────────
        scrapers = list(SCRAPERS_PRIMARY)
        if options["include_jobspy"] and SCRAPERS_JOBSPY:
            scrapers += SCRAPERS_JOBSPY

        # Filter by tier
        if options["gov_only"]:
            scrapers = [s for s in scrapers if s[3] in GOV_PLATFORMS]
        elif options["it_only"]:
            scrapers = [s for s in scrapers if s[3] in IT_PLATFORMS]
        elif options["email_only"]:
            scrapers = [s for s in scrapers if s[2] in ("high", "gov")]

        # Filter by explicit slug list
        if options["scrapers"]:
            wanted = set(options["scrapers"])
            scrapers = [s for s in scrapers if s[3] in wanted]
            if not scrapers:
                self.stderr.write(
                    f"No matching scrapers for: {options['scrapers']}\n"
                    f"Available slugs: {[s[3] for s in SCRAPERS_PRIMARY]}"
                )
                return

        # ── Existing URL cache for dedup ──────────────────────────────────────
        existing_urls = set()
        if skip_existing:
            existing_urls = set(Job.objects.exclude(url="").values_list("url", flat=True))
            self.stdout.write(f"[skip-existing] {len(existing_urls)} URLs already in DB\n")

        self.stdout.write(
            f"Keywords: '{keywords}' | max_jobs={'unlimited' if not max_jobs else max_jobs} "
            f"| scrapers={len(scrapers)} | workers={workers}\n"
        )

        all_jobs = []

        # ── Run scrapers ──────────────────────────────────────────────────────
        def _run_scraper(name, fn, tier, slug):
            kw = keywords
            # Inject priority keywords for gov scrapers when no explicit search
            if slug in {"sayouth", "essa", "govza"} and not user_set_keywords:
                kw = f"{keywords} {GOV_PRIORITY_KW}"

            # Determine limit & pages to pass
            limit_arg = max_jobs if max_jobs else 9999
            pages_arg = max_pages if max_pages else SCRAPER_MAX_PAGES.get(name, 30)

            try:
                # All scrapers accept (keywords, limit) — max_pages handled internally
                # by the scrapers themselves using their own pagination loops.
                # We pass limit=limit_arg so they know when to stop collecting.
                results = fn(kw, limit=limit_arg)

                # Filter out URLs already in DB
                if skip_existing and existing_urls:
                    before = len(results)
                    results = [j for j in results if j.get("url") not in existing_urls]
                    skipped_url = before - len(results)
                else:
                    skipped_url = 0

                email_count = sum(1 for j in results if j.get("apply_email"))
                self.stdout.write(
                    f"  [{tier.upper():6}] {name:<20} {len(results):>4} new jobs "
                    f"({email_count} with email"
                    + (f", {skipped_url} skipped/existing" if skipped_url else "")
                    + ")"
                )
                return results

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  [{tier.upper():6}] {name:<20} FAILED — {e}"))
                return []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_run_scraper, name, fn, tier, slug): name
                for name, fn, tier, slug in scrapers
            }
            for future in as_completed(futures):
                try:
                    all_jobs += future.result()
                except Exception:
                    pass

        # ── Deduplicate across scrapers before DB write ───────────────────────
        seen_keys = set()
        deduped = []
        for j in all_jobs:
            key = (
                (j.get("title") or "").strip().lower()[:80],
                (j.get("company") or "").strip().lower()[:60],
                (j.get("platform") or "").strip().lower(),
            )
            if key not in seen_keys and j.get("title"):
                seen_keys.add(key)
                deduped.append(j)

        self.stdout.write(f"\n{len(all_jobs)} total scraped → {len(deduped)} after cross-scraper dedup\n")

        # ── Write to DB ───────────────────────────────────────────────────────
        created = updated = skipped = errors = 0

        for j in deduped:
            title    = _t(j.get("title"),    255)
            company  = _t(j.get("company"),  255)
            platform = _t(j.get("platform"), 50)

            if not title:
                continue

            try:
                obj, new = Job.objects.get_or_create(
                    title=title,
                    company=company,
                    platform=platform,
                    defaults={
                        "location":      _t(j.get("location"),    255),
                        "description":   j.get("description",     ""),
                        "url":           j.get("url",             ""),
                        "apply_email":   _t(j.get("apply_email"), 255),
                        "salary":        _t(j.get("salary"),      255),
                        "job_type":      _t(j.get("job_type"),    100),
                        "how_to_apply":  j.get("how_to_apply",    ""),
                        "docs_required": j.get("docs_required",   ""),
                    },
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  DB error '{title}': {e}"))
                errors += 1
                continue

            if new:
                created += 1
            else:
                # Opportunistically fill in missing fields on existing records
                dirty = []
                if not obj.apply_email and j.get("apply_email"):
                    obj.apply_email = _t(j["apply_email"], 255); dirty.append("apply_email")
                if not obj.salary and j.get("salary"):
                    obj.salary = _t(j["salary"], 255); dirty.append("salary")
                if not obj.job_type and j.get("job_type"):
                    obj.job_type = _t(j["job_type"], 100); dirty.append("job_type")
                if not obj.how_to_apply and j.get("how_to_apply"):
                    obj.how_to_apply = j["how_to_apply"]; dirty.append("how_to_apply")
                if not obj.docs_required and j.get("docs_required"):
                    obj.docs_required = j["docs_required"]; dirty.append("docs_required")
                if (not obj.description or len(obj.description) < 100) and j.get("description"):
                    obj.description = j["description"]; dirty.append("description")
                if dirty:
                    obj.save(update_fields=dirty)
                    updated += 1
                else:
                    skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n{'─'*50}\n"
            f"  ✓ Created : {created} new jobs\n"
            f"  ↑ Updated : {updated} existing jobs (filled missing fields)\n"
            f"  = Skipped : {skipped} already complete\n"
            f"  ✗ Errors  : {errors}\n"
            f"  TOTAL DB  : {Job.objects.count()} jobs\n"
            f"{'─'*50}"
        ))
