"""Thin Ollama client (stdlib only) with retry on transient errors."""
import json
import time
import urllib.error
import urllib.request

from app import config


def _post(path: str, body: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        config.OLLAMA_URL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def retry(fn, attempts: int = 3):
    """Call fn(); on 5xx / connection errors sleep 2s, 4s and try again. Anything else raises immediately."""
    for i in range(attempts):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == attempts - 1:
                raise
            time.sleep(2 ** (i + 1))
        except urllib.error.URLError:
            if i == attempts - 1:
                raise
            time.sleep(2 ** (i + 1))


def require_ollama() -> None:
    try:
        with urllib.request.urlopen(config.OLLAMA_URL + "/api/tags", timeout=5) as r:
            have = {m["name"] for m in json.load(r)["models"]}
    except urllib.error.URLError:
        raise SystemExit(f"Ollama is not reachable at {config.OLLAMA_URL}. Install it from https://ollama.com and start it.")
    have |= {n.removesuffix(":latest") for n in have}
    if config.SQL_MODEL not in have:
        raise SystemExit(f"Model '{config.SQL_MODEL}' is not pulled. Run: ollama pull {config.SQL_MODEL}")


def generate(prompt: str, num_predict: int = 400) -> str:
    res = retry(lambda: _post("/api/generate", {
        "model": config.SQL_MODEL,
        "prompt": prompt,
        "stream": False,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": num_predict},
    }))
    return res["response"].strip()
