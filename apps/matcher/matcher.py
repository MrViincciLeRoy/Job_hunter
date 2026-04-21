import json
import os
from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def match_job_to_cv(cv_data: dict, job: dict) -> int:
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
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
