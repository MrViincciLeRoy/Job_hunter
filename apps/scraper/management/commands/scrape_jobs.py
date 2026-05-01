from django.core.management.base import BaseCommand
from django.db import close_old_connections
from concurrent.futures import ThreadPoolExecutor, as_completed
from apps.scraper.scrapers.pnet import scrape_pnet
from apps.scraper.scrapers.careerjunction import scrape_careerjunction, scrape_careerjunction_it
from apps.scraper.scrapers.careers24 import scrape_careers24
from apps.scraper.scrapers.jobmail import scrape_jobmail
from apps.scraper.scrapers.gumtree import scrape_gumtree
from apps.scraper.scrapers.govjobs import scrape_dpsa, scrape_sayouth, scrape_essa, scrape_govza
from apps.scraper.models import Job
from apps.cv.models import CV

JOB_TYPE_MAP = {
    'internship':  ['internship'],
    'learnership': ['learnership'],
    'bursary':     ['bursary', 'scholarship'],
    'scholarship': ['scholarship', 'bursary'],
    'graduate':    ['graduate'],
    'entry_level': ['entry level'],
    'low_barrier': ['entry level'],
    'permanent':   ['Government / Permanent', 'Permanent'],
    'all':         [],
}

FRIENDLY_NAMES = {
    'internship':  'Internships',
    'learnership': 'Learnerships',
    'bursary':     'Bursaries / Scholarships',
    'scholarship': 'Scholarships',
    'graduate':    'Graduate Programmes',
    'entry_level': 'Entry Level (Grade 12)',
    'low_barrier': 'Low Barrier (Grade 10–12 / ABET)',
    'permanent':   'Permanent / General Government',
    'all':         'All Job Types',
}

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

GOV_PLATFORMS   = {"dpsa", "sayouth", "essa", "govza"}
IT_PLATFORMS    = {"pnet", "careerjunction", "careerjunction_it"}
GOV_PRIORITY_KW = "internship learnership entry level graduate IT"
GOV_PDF_SCRAPERS = {'dpsa'}

SCRAPER_MAX_PAGES = {
    "DPSA":              1,
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


def _job_passes_type_filter(job, allowed_job_types):
    if not allowed_job_types:
        return True
    jt = (job.get('job_type') or '').lower().strip()
    if jt in allowed_job_types:
        return True
    if 'entry level' in allowed_job_types and job.get('_low_barrier'):
        return True
    for allowed in allowed_job_types:
        if allowed in jt:
            return True
    return False


def _resolve_type_filter(type_slugs):
    if not type_slugs or 'all' in type_slugs:
        return set()
    resolved = set()
    for slug in type_slugs:
        resolved.update(JOB_TYPE_MAP.get(slug, [slug]))
    return resolved


class Command(BaseCommand):
    help = "Bulk-scrape jobs from SA/gov platforms — filter by job type"

    def add_arguments(self, parser):
        parser.add_argument("--keywords",       type=str,   default=None)
        parser.add_argument("--max-jobs",       type=int,   default=0)
        parser.add_argument("--max-pages",      type=int,   default=0)
        parser.add_argument("--email-only",     action="store_true")
        parser.add_argument("--gov-only",       action="store_true")
        parser.add_argument("--it-only",        action="store_true")
        parser.add_argument("--include-jobspy", action="store_true")
        parser.add_argument("--workers",        type=int,   default=4)
        parser.add_argument("--scrapers",       nargs="*",  default=None)
        parser.add_argument("--no-skip",        action="store_true")
        parser.add_argument(
            "--types",
            nargs="*",
            default=["all"],
            metavar="TYPE",
            help=(
                "Job types to include. Space-separated. "
                "Options: internship learnership bursary scholarship graduate "
                "entry_level low_barrier permanent all. "
                "Default: all"
            ),
        )

    def handle(self, *args, **options):
        cv = CV.objects.filter(active=True).last()
        if not cv:
            self.stderr.write("No active CV. Upload one first via /upload-cv/")
            return

        type_slugs  = options.get("types") or ["all"]
        type_filter = _resolve_type_filter(type_slugs)

        if type_filter:
            labels = [FRIENDLY_NAMES.get(s, s) for s in type_slugs if s != 'all']
            self.stdout.write(f"Type filter: {', '.join(labels)}\n")
        else:
            self.stdout.write("Type filter: ALL (no filter)\n")

        keywords = options.get("keywords")
        user_set_keywords = bool(keywords)
        if not keywords:
            skills = cv.parsed_data.get("skills", [])
            keywords = " ".join(skills[:4]) if skills else "developer"

        if type_filter and not user_set_keywords:
            extra_kw = []
            if 'internship' in type_filter:
                extra_kw.append('internship')
            if 'learnership' in type_filter:
                extra_kw.append('learnership')
            if 'bursary' in type_filter or 'scholarship' in type_filter:
                extra_kw.append('bursary')
            if extra_kw:
                keywords = f"{keywords} {' '.join(extra_kw)}"

        max_jobs      = options["max_jobs"]
        workers       = options["workers"]
        skip_existing = not options.get("no_skip", False)

        scrapers = list(SCRAPERS_PRIMARY)
        if options["include_jobspy"] and SCRAPERS_JOBSPY:
            scrapers += SCRAPERS_JOBSPY

        if options["gov_only"]:
            scrapers = [s for s in scrapers if s[3] in GOV_PLATFORMS]
        elif options["it_only"]:
            scrapers = [s for s in scrapers if s[3] in IT_PLATFORMS]
        elif options["email_only"]:
            scrapers = [s for s in scrapers if s[2] in ("high", "gov")]

        if options["scrapers"]:
            wanted = set(options["scrapers"])
            scrapers = [s for s in scrapers if s[3] in wanted]
            if not scrapers:
                self.stderr.write(f"No matching scrapers: {options['scrapers']}")
                return

        existing_urls = set()
        if skip_existing:
            existing_urls = set(Job.objects.exclude(url="").values_list("url", flat=True))
            self.stdout.write(f"[skip-existing] {len(existing_urls)} URLs already in DB\n")

        self.stdout.write(
            f"Keywords: '{keywords}' | max_jobs={'unlimited' if not max_jobs else max_jobs} "
            f"| scrapers={len(scrapers)} | workers={workers}\n"
        )

        all_jobs = []

        def _run_scraper(name, fn, tier, slug):
            kw = None
            if slug in {"sayouth", "essa", "govza"} and not user_set_keywords:
                kw = f"{keywords} {GOV_PRIORITY_KW}"

            limit_arg = max_jobs if max_jobs else 9999

            try:
                results = fn(kw, limit=limit_arg)

                if type_filter and slug not in GOV_PDF_SCRAPERS:
                    before = len(results)
                    results = [j for j in results if _job_passes_type_filter(j, type_filter)]
                    filtered_out = before - len(results)
                else:
                    filtered_out = 0

                if skip_existing and existing_urls:
                    before = len(results)
                    results = [j for j in results if j.get("url") not in existing_urls]
                    skipped_url = before - len(results)
                else:
                    skipped_url = 0

                email_count = sum(1 for j in results if j.get("apply_email"))
                msg = (
                    f"  [{tier.upper():6}] {name:<20} {len(results):>4} jobs"
                    f" ({email_count} with email"
                )
                if filtered_out:
                    msg += f", {filtered_out} filtered by type"
                if skipped_url:
                    msg += f", {skipped_url} skipped/existing"
                msg += ")"
                self.stdout.write(msg)
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

        self.stdout.write(f"\n{len(all_jobs)} total → {len(deduped)} after dedup\n")

        type_counts = {}
        for j in deduped:
            jt = j.get('job_type', 'unknown')
            type_counts[jt] = type_counts.get(jt, 0) + 1
        if type_counts:
            self.stdout.write("Type breakdown:\n")
            for jt, count in sorted(type_counts.items(), key=lambda x: -x[1]):
                self.stdout.write(f"  {jt:<30} {count}\n")

        # ── Write to DB ───────────────────────────────────────────────────────
        # Refresh DB connections — Neon closes idle connections after ~5 min.
        # The thread pool keeps the process alive past that timeout, so we
        # must discard stale connections before touching the DB again.
        close_old_connections()

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
                dirty = []
                for field, max_len in [("apply_email", 255), ("salary", 255), ("job_type", 100)]:
                    if not getattr(obj, field) and j.get(field):
                        setattr(obj, field, _t(j[field], max_len))
                        dirty.append(field)
                for field in ["how_to_apply", "docs_required", "description"]:
                    if not getattr(obj, field) and j.get(field):
                        setattr(obj, field, j[field])
                        dirty.append(field)
                if dirty:
                    obj.save(update_fields=dirty)
                    updated += 1
                else:
                    skipped += 1

        close_old_connections()
        self.stdout.write(self.style.SUCCESS(
            f"\n{'─'*50}\n"
            f"  ✓ Created : {created}\n"
            f"  ↑ Updated : {updated}\n"
            f"  = Skipped : {skipped}\n"
            f"  ✗ Errors  : {errors}\n"
            f"  TOTAL DB  : {Job.objects.count()}\n"
            f"{'─'*50}"
        ))