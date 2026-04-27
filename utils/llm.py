import os
import time
import random
import json
import requests
from groq import Groq, RateLimitError

# --- Groq (scraping, CV parsing, cover letters) ---
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
GROQ_MODEL = "llama-3.3-70b-versatile"

# --- HF (matching only) ---
HF_API_KEY = os.getenv("HF_API_KEY")
HF_MODEL = os.getenv("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")
HF_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"

MIN_DELAY = 2.0
MAX_DELAY = 5.0


# --- Shared response wrapper ---
class _Message:
    def __init__(self, content):
        self.content = content

class _Choice:
    def __init__(self, content):
        self.message = _Message(content)

class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


# --- HF helpers ---
def _build_prompt(messages):
    parts = []
    for m in messages:
        role, content = m["role"], m["content"]
        if role == "system":
            parts.append(f"<s>[INST] <<SYS>>\n{content}\n<</SYS>>\n")
        elif role == "user":
            parts.append(f"{content} [/INST]")
        elif role == "assistant":
            parts.append(f"{content} </s><s>[INST] ")
    return "".join(parts)


def _extract_json(text):
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        return text[start:end]
    return text


# --- Groq call (CV parsing, cover letters, spider) ---
def groq_call(messages, model=GROQ_MODEL, response_format=None, retries=4):
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    for attempt in range(retries):
        try:
            kwargs = dict(model=model, messages=messages)
            if response_format:
                kwargs["response_format"] = response_format
            return groq_client.chat.completions.create(**kwargs)
        except RateLimitError:
            wait = (2 ** attempt) * 15 + random.uniform(0, 10)
            print(f"[Groq] Rate limited. Waiting {wait:.1f}s (attempt {attempt+1}/{retries})")
            time.sleep(wait)
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"[Groq] Error: {e}. Retrying in 10s...")
            time.sleep(10)
    raise RuntimeError("Groq call failed after all retries")


# --- HF call (matching only) ---
def hf_call(messages, response_format=None, retries=4):
    time.sleep(random.uniform(1.5, 3.0))

    prompt = _build_prompt(messages)
    if response_format and response_format.get("type") == "json_object":
        prompt += "\n\nRespond with valid JSON only. No explanation, no markdown."

    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 256,
            "temperature": 0.2,
            "return_full_text": False,
        }
    }

    for attempt in range(retries):
        try:
            r = requests.post(HF_URL, headers=headers, json=payload, timeout=60)

            if r.status_code == 503:
                wait = 20 + (attempt * 10)
                print(f"[HF] Model loading, waiting {wait}s...")
                time.sleep(wait)
                continue

            if r.status_code == 429:
                wait = (2 ** attempt) * 10
                print(f"[HF] Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            r.raise_for_status()
            result = r.json()

            text = result[0].get("generated_text", "") if isinstance(result, list) else result.get("generated_text", "")

            if response_format and response_format.get("type") == "json_object":
                text = _extract_json(text)
                json.loads(text)  # validate

            return _Response(text)

        except json.JSONDecodeError:
            print(f"[HF] Bad JSON on attempt {attempt+1}, retrying...")
            if attempt == retries - 1:
                return _Response('{"score": 0, "reason": "parse error"}')

        except Exception as e:
            print(f"[HF] Error: {e}. Attempt {attempt+1}/{retries}")
            if attempt == retries - 1:
                raise
            time.sleep(10)

    raise RuntimeError("HF call failed after all retries")