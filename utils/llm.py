import os
import time
import random
import json
import requests
from groq import Groq, RateLimitError

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
GROQ_MODEL = "llama-3.3-70b-versatile"

HF_API_KEY = os.getenv("HF_API_KEY")
HF_MODELS = [
    "HuggingFaceH4/zephyr-7b-beta",
    "mistralai/Mistral-7B-Instruct-v0.1",
    "tiiuae/falcon-7b-instruct",
]

MIN_DELAY = 2.0
MAX_DELAY = 5.0


class _Message:
    def __init__(self, content):
        self.content = content

class _Choice:
    def __init__(self, content):
        self.message = _Message(content)

class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


def _extract_json(text):
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        return text[start:end]
    return text


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


def hf_call(messages, response_format=None, retries=3):
    time.sleep(random.uniform(1.5, 3.0))

    user_content = next((m["content"] for m in messages if m["role"] == "user"), "")
    if response_format and response_format.get("type") == "json_object":
        prompt = f"<|user|>\n{user_content}\nRespond with valid JSON only. No explanation.\n<|assistant|>"
    else:
        prompt = f"<|user|>\n{user_content}\n<|assistant|>"

    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 256,
            "temperature": 0.2,
            "return_full_text": False,
        }
    }
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}

    for model in HF_MODELS:
        url = f"https://api-inference.huggingface.co/models/{model}"
        print(f"[HF] Trying {model}")
        for attempt in range(retries):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=60)

                if r.status_code == 404:
                    print(f"[HF] {model} not found, trying next model...")
                    break

                if r.status_code == 503:
                    wait = 20 + (attempt * 10)
                    print(f"[HF] {model} loading, waiting {wait}s...")
                    time.sleep(wait)
                    continue

                if r.status_code == 429:
                    wait = (2 ** attempt) * 10
                    print(f"[HF] Rate limited on {model}, waiting {wait}s...")
                    time.sleep(wait)
                    continue

                r.raise_for_status()
                result = r.json()
                text = result[0].get("generated_text", "") if isinstance(result, list) else result.get("generated_text", "")

                if response_format and response_format.get("type") == "json_object":
                    text = _extract_json(text)
                    json.loads(text)

                print(f"[HF] Success with {model}")
                return _Response(text)

            except json.JSONDecodeError:
                print(f"[HF] Bad JSON from {model} attempt {attempt+1}, retrying...")
                if attempt == retries - 1:
                    break

            except Exception as e:
                print(f"[HF] Error on {model}: {e}. Attempt {attempt+1}/{retries}")
                if attempt == retries - 1:
                    break
                time.sleep(10)

    print("[HF] All models failed, returning default score")
    return _Response('{"score": 0, "reason": "all models failed"}')