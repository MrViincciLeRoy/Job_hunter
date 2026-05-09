from datetime import date
from apps.accounts.models import WorkExperience, Education, Skill

NQF_RANK = {"4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "other": 7}

LEVEL_XP = {
    range(5, 7):   0,
    range(7, 9):   2,
    range(9, 11):  3,
    range(11, 13): 5,
    range(13, 15): 8,
}

SPECIAL_FLAGS = [
    ("driver",           "drivers_licence",  "Valid driver's licence"),
    ("saqa",             "saqa",             "SAQA verification"),
    ("ecsa",             "professional_reg", "ECSA registration"),
    ("sacpcmp",          "professional_reg", "SACPCMP registration"),
    ("professional bod", "professional_reg", "Professional body registration"),
    ("nyukela",          None,               "SMS Pre-entry (Nyukela) certificate"),
    ("sms pre-entry",    None,               "SMS Pre-entry (Nyukela) certificate"),
    ("security clearance", None,             "Security clearance"),
    ("own transport",    None,               "Own transport"),
    ("persal",           None,               "PERSAL proficiency"),
    ("bas ",             None,               "BAS system proficiency"),
    ("sap ",             None,               "SAP proficiency"),
]


def _total_experience_years(user):
    total = 0
    for exp in WorkExperience.objects.filter(user=user):
        end = date.today() if exp.is_current else (exp.end_date or date.today())
        months = (end.year - exp.start_date.year) * 12 + (end.month - exp.start_date.month)
        total += max(0, months)
    return round(total / 12, 1)


def _extract_required_nqf(description: str) -> int | None:
    desc = description.lower()
    if "doctoral" in desc or "phd" in desc:              return 10
    if "master" in desc:                                  return 9
    if "honours" in desc or "postgrad diploma" in desc:   return 8
    if "degree" in desc or "bachelor" in desc:            return 7
    if "advanced diploma" in desc:                        return 7
    if "diploma" in desc:                                 return 6
    if "higher certificate" in desc:                      return 5
    if "matric" in desc or "grade 12" in desc:            return 4
    return None


def _extract_required_years(description: str) -> int:
    import re
    patterns = [
        r"(\d+)\+?\s*years?\s*(of\s+)?experience",
        r"minimum\s+(\d+)\s*years?",
        r"at\s+least\s+(\d+)\s*years?",
    ]
    for pat in patterns:
        m = re.search(pat, description.lower())
        if m:
            return int(m.group(1))
    return 0


def _extract_salary_level(description: str) -> int | None:
    import re
    m = re.search(r"level\s+(\d{1,2})", description.lower())
    return int(m.group(1)) if m else None


def _skills_score(user, description: str) -> tuple[int, list, list]:
    desc = description.lower()
    user_skills = [s.name.lower() for s in Skill.objects.filter(user=user)]
    matched, missing = [], []
    for skill in user_skills:
        (matched if skill in desc else missing).append(skill)
    total_mentioned = max(len(user_skills), 1)
    score = int(len(matched) / total_mentioned * 100)
    return score, matched, missing


def run_qualification_check(user, job) -> dict:
    desc = (job.description or "") + " " + (job.title or "")
    result = {
        "verdict":       "PROCEED",
        "education":     {"status": "✅", "reason": ""},
        "experience":    {"status": "✅", "reason": ""},
        "skills":        {"status": "✅", "score": 0, "matched": [], "missing": []},
        "special_flags": [],
        "disqualified":  False,
        "warnings":      [],
    }

    # ── Education ─────────────────────────────────────────────────────────────
    req_nqf = _extract_required_nqf(desc)
    if req_nqf:
        user_edu = Education.objects.filter(user=user).order_by("-nqf_level").first()
        user_nqf = NQF_RANK.get(user_edu.nqf_level, 0) if user_edu else 0
        if user_nqf < req_nqf:
            result["education"] = {
                "status": "❌",
                "reason": f"NQF {req_nqf} required, user has NQF {user_nqf or 'unknown'}",
            }
            result["disqualified"] = True
            result["verdict"] = "DISQUALIFY"
        elif user_nqf == req_nqf:
            result["education"]["reason"] = f"NQF {user_nqf} — meets requirement"
        else:
            result["education"]["reason"] = f"NQF {user_nqf} — exceeds NQF {req_nqf} requirement"
    else:
        result["education"]["reason"] = "No specific NQF requirement detected"

    # ── Experience ────────────────────────────────────────────────────────────
    req_years = _extract_required_years(desc)
    sal_level = _extract_salary_level(desc)
    if not req_years and sal_level:
        for rng, yrs in LEVEL_XP.items():
            if sal_level in rng:
                req_years = yrs
                break

    user_years = _total_experience_years(user)
    if req_years:
        if user_years < req_years:
            result["experience"] = {
                "status": "❌",
                "reason": f"{req_years} yrs required, user has {user_years} yrs",
            }
            result["disqualified"] = True
            result["verdict"] = "DISQUALIFY"
        elif user_years < req_years + 1:
            result["experience"] = {
                "status": "⚠️",
                "reason": f"Close match: {req_years} yrs required, user has {user_years} yrs",
            }
            result["warnings"].append("Experience is close to minimum requirement")
            if result["verdict"] == "PROCEED":
                result["verdict"] = "NEEDS CONFIRMATION"
        else:
            result["experience"]["reason"] = f"{user_years} yrs — meets {req_years} yr requirement"
    else:
        result["experience"]["reason"] = f"No specific requirement detected ({user_years} yrs on profile)"

    # ── Skills ────────────────────────────────────────────────────────────────
    score, matched, missing = _skills_score(user, desc)
    result["skills"] = {"score": score, "matched": matched, "missing": missing}
    if score < 40:
        result["skills"]["status"] = "❌"
        result["disqualified"] = True
        result["verdict"] = "DISQUALIFY"
    elif score < 60:
        result["skills"]["status"] = "⚠️"
        result["warnings"].append(f"Weak skill match ({score}%) — consider updating profile")
        if result["verdict"] == "PROCEED":
            result["verdict"] = "NEEDS CONFIRMATION"
    else:
        result["skills"]["status"] = "✅"

    # ── Special flags ─────────────────────────────────────────────────────────
    for keyword, doc_type, label in SPECIAL_FLAGS:
        if keyword in desc.lower():
            result["special_flags"].append({
                "label":    label,
                "doc_type": doc_type,
                "keyword":  keyword,
            })

    return result
