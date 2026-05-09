from apps.accounts.models import UserDocument

LABEL = dict([
    ("cv",               "CV / Resume"),
    ("z83",              "Z83 Form"),
    ("id_document",      "ID Document"),
    ("matric",           "Matric Certificate"),
    ("qualifications",   "Qualifications / Certificates"),
    ("certified_copies", "Certified Copies"),
    ("saqa",             "SAQA Verification"),
    ("drivers_licence",  "Driver's Licence"),
    ("police_clearance", "Police Clearance Certificate"),
    ("professional_reg", "Professional Body Registration"),
    ("cover_letter",     "Cover Letter"),
    ("portfolio",        "Portfolio / Work Samples"),
    ("references",       "References"),
])

GOV_PLATFORMS = {"dpsa", "sayouth", "essa", "govza"}

# (keyword_in_desc, doc_type, mandatory_for_gov, mandatory_for_private)
CONDITIONAL_RULES = [
    ("saqa",                 "saqa",             True,  False),
    ("foreign qualification","saqa",             True,  False),
    ("driver",               "drivers_licence",  True,  False),
    ("police clearance",     "police_clearance", False, False),
    ("professional reg",     "professional_reg", False, False),
    ("ecsa",                 "professional_reg", True,  False),
    ("sacpcmp",              "professional_reg", True,  False),
    ("certified copies",     "certified_copies", True,  False),
    ("cover letter",         "cover_letter",     False, True),
    ("portfolio",            "portfolio",        False, False),
    ("references",           "references",       False, False),
]


def _get_primary_cv(user):
    doc = UserDocument.objects.filter(user=user, doc_type="cv", is_primary=True).first()
    if not doc:
        doc = UserDocument.objects.filter(user=user, doc_type="cv").first()
    return doc


def _get_doc(user, doc_type):
    return UserDocument.objects.filter(user=user, doc_type=doc_type).first()


def resolve_documents(user, job) -> dict:
    """
    Returns:
        {
            "attachments": [(UserDocument, safe_filename), ...],
            "missing":     [(doc_type, label, mandatory), ...],
            "summary":     [{"label": str, "status": "✅"|"❌"|"⚠️", "doc_type": str}],
        }
    """
    platform = (job.platform or "").lower()
    # Include docs_required field in scan so DPSA-extracted doc requirements are caught
    desc = " ".join(filter(None, [
        job.description or "",
        job.title or "",
        job.docs_required or "",
        job.how_to_apply or "",
    ])).lower()
    is_gov = platform in GOV_PLATFORMS

    attachments = []
    missing     = []
    summary     = []

    def _attach(doc, label):
        safe = doc.file_name.replace(" ", "_")
        attachments.append((doc, safe))
        summary.append({"label": label, "status": "✅", "doc_type": doc.doc_type})

    def _missing(doc_type, label, mandatory):
        missing.append((doc_type, label, mandatory))
        summary.append({"label": label, "status": "❌" if mandatory else "⚠️", "doc_type": doc_type})

    # ── CV (always mandatory) ─────────────────────────────────────────────────
    cv = _get_primary_cv(user)
    if cv:
        _attach(cv, "CV (primary)")
    else:
        _missing("cv", LABEL["cv"], mandatory=True)

    # ── Government mandatory docs ─────────────────────────────────────────────
    if is_gov:
        for dt in ("z83", "id_document", "matric"):
            doc = _get_doc(user, dt)
            if doc:
                _attach(doc, LABEL[dt])
            else:
                _missing(dt, LABEL[dt], mandatory=True)

        # Qualifications mandatory if degree/diploma required
        if any(kw in desc for kw in ("degree", "diploma", "honours", "master", "doctoral", "phd", "nqf")):
            doc = _get_doc(user, "qualifications")
            if doc:
                _attach(doc, LABEL["qualifications"])
            else:
                _missing("qualifications", LABEL["qualifications"], mandatory=True)

    # ── Private sector cover letter ───────────────────────────────────────────
    if not is_gov and "cover letter" in desc:
        doc = _get_doc(user, "cover_letter")
        if doc:
            _attach(doc, LABEL["cover_letter"])
        else:
            _missing("cover_letter", LABEL["cover_letter"], mandatory=True)

    # ── Conditional rules ─────────────────────────────────────────────────────
    seen_types = {dt for _, dt, _ in missing} | {d.doc_type for d, _ in attachments}

    for keyword, doc_type, req_gov, req_private in CONDITIONAL_RULES:
        if doc_type in seen_types:
            continue
        if keyword not in desc:
            continue
        mandatory = req_gov if is_gov else req_private
        doc = _get_doc(user, doc_type)
        if doc:
            _attach(doc, LABEL.get(doc_type, doc_type))
        else:
            _missing(doc_type, LABEL.get(doc_type, doc_type), mandatory=mandatory)
        seen_types.add(doc_type)

    return {
        "attachments": attachments,
        "missing":     missing,
        "summary":     summary,
    }


def check_size_limit(attachments, limit_mb=10) -> tuple[bool, float]:
    total_bytes = sum(doc.file_size for doc, _ in attachments)
    total_mb    = total_bytes / (1024 * 1024)
    return total_mb <= limit_mb, round(total_mb, 2)
