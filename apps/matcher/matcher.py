import json
from utils.llm import hf_call


def _match_job_to_cv(cv_data: dict, job: dict) -> int:
    response = hf_call(
        messages=[{
            "role": "user",
            "content": f"""Score this CV-to-job match from 0-100. Return ONLY JSON: {{"score": int, "reason": str}}

CV Skills: {cv_data.get('skills', [])}
CV Experience: {cv_data.get('experience', [])}
Job Title: {job.get('title')}
Job Description: {str(job.get('description', ''))[:800]}"""
        }],
        response_format={"type": "json_object"},
    )
    try:
        return int(json.loads(response.choices[0].message.content).get("score", 0))
    except Exception:
        return 0

# apps/matcher/matcher.py
from utils.matcher_algo import batch_match

def match_job_to_cv(cv_data: dict, job: dict) -> int:
    scores = batch_match(cv_data, [job])
    return scores[0]