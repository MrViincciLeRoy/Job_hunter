import time
import random
import os
from groq import Groq, RateLimitError

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MODEL = "llama-3.3-70b-versatile"
MIN_DELAY = 2.0
MAX_DELAY = 5.0


def groq_call(messages, model=MODEL, response_format=None, retries=4):
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    for attempt in range(retries):
        try:
            kwargs = dict(model=model, messages=messages)
            if response_format:
                kwargs["response_format"] = response_format
            return client.chat.completions.create(**kwargs)
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
