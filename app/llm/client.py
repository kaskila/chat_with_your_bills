"""Thin wrapper around the Ollama HTTP API (via the ``ollama`` package).

Every call has a timeout, is retried once on transient errors, keeps the model
loaded (``keep_alive``), runs with thinking off and temperature 0, and reports
Ollama's own timing statistics.
"""

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
import ollama

from app.config import get_settings


class LLMError(RuntimeError):
    """Ollama is unreachable, the model is missing, or the call timed out."""


@dataclass
class ChatResult:
    content: str
    model: str
    seconds: float            # wall-clock time of the call
    load_s: float             # model loading (0 when already in memory)
    prompt_tokens: int
    prompt_s: float
    output_tokens: int
    output_s: float

    def stats(self) -> dict:
        return {
            "model": self.model, "seconds": round(self.seconds, 2), "load_s": round(self.load_s, 2),
            "prompt_tokens": self.prompt_tokens, "prompt_s": round(self.prompt_s, 2),
            "output_tokens": self.output_tokens, "output_s": round(self.output_s, 2),
            "tokens_per_s": round(self.output_tokens / self.output_s, 1) if self.output_s else None,
        }


@lru_cache(maxsize=8)
def _client(host: str, timeout: float) -> ollama.Client:
    return ollama.Client(host=host, timeout=timeout)


@lru_cache(maxsize=1)
def physical_cores() -> int | None:
    """Physical CPU cores (not hyper-threads), or None if unknown.

    On the i7-1355U (2 performance + 8 efficiency cores, 12 threads) Ollama's own default
    used 6 threads; 10 (all physical cores) wrote 12% faster than 6, 8 was +9%, 12 only +4%."""
    try:
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "(Get-CimInstance Win32_Processor | Measure-Object NumberOfCores -Sum).Sum"],
                                 capture_output=True, text=True, timeout=15, creationflags=flags).stdout
            return int(out.strip()) or None
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.physicalcpu"], capture_output=True, text=True, timeout=5).stdout
            return int(out.strip()) or None
        cores = set()
        physical = None
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "physical id":
                physical = value.strip()
            elif key.strip() == "core id":
                cores.add((physical, value.strip()))
        return len(cores) or None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _options(**overrides) -> dict:
    s = get_settings()
    options = {"temperature": 0, "seed": 42, "num_ctx": s.num_ctx}
    threads = s.num_thread or physical_cores()  # setting, else all physical cores (measured fastest)
    if threads:
        options["num_thread"] = threads
    options.update({k: v for k, v in overrides.items() if v is not None})
    return options


def _ns(value) -> float:
    return (value or 0) / 1e9


def chat(model: str, messages: list[dict], *, format: dict | str | None = None,
         timeout: float | None = None, images: list[bytes] | None = None, **options) -> ChatResult:
    """One chat call. ``format`` may be a JSON schema to force structured output."""
    s = get_settings()
    timeout = timeout or s.extract_timeout_s
    if images:
        messages = [*messages[:-1], {**messages[-1], "images": images}]

    last_error: Exception | None = None
    for attempt in range(s.llm_retries + 1):
        started = time.perf_counter()
        try:
            response = _client(s.ollama_host, timeout).chat(
                model=model, messages=messages, format=format, think=False,
                options=_options(**options), keep_alive=s.keep_alive, stream=False,
            )
        except ollama.ResponseError as error:
            if error.status_code == 404:
                raise LLMError(f"Model '{model}' is not installed. Run: ollama pull {model}") from error
            last_error = error
        except httpx.TimeoutException as error:
            # Not retried: on a slow (e.g. battery-throttled) CPU a retry only doubles the wait.
            raise LLMError(f"Timed out: '{model}' did not answer within {timeout:.0f} s. "
                           "On a laptop, plug in the charger; or raise BILLS_EXTRACT_TIMEOUT_S.") from error
        except (httpx.ConnectError, ConnectionError) as error:
            raise LLMError(f"Cannot reach Ollama at {s.ollama_host}. Is it running?") from error
        else:
            return ChatResult(
                content=response.message.content or "",
                model=model,
                seconds=time.perf_counter() - started,
                load_s=_ns(response.load_duration),
                prompt_tokens=response.prompt_eval_count or 0,
                prompt_s=_ns(response.prompt_eval_duration),
                output_tokens=response.eval_count or 0,
                output_s=_ns(response.eval_duration),
            )
        if attempt < s.llm_retries:
            time.sleep(1.0)
    raise last_error if isinstance(last_error, LLMError) else LLMError(f"Ollama call failed: {last_error}")


def ollama_reachable(timeout: float = 3.0) -> bool:
    try:
        httpx.get(f"{get_settings().ollama_host}/api/tags", timeout=timeout).raise_for_status()
        return True
    except httpx.HTTPError:
        return False


def _ollama_programs() -> list[list[str]]:
    """Ways to start Ollama on this computer: its tray app (Windows), else ``ollama serve``."""
    found = []
    exe = shutil.which("ollama") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe")
    tray = Path(exe).with_name("ollama app.exe")
    if tray.exists():
        found.append([str(tray)])
    if Path(exe).exists():
        found.append([exe, "serve"])
    return found


def ensure_ollama(wait_s: float = 45.0) -> bool:
    """Ollama answers, or was started and answers within ``wait_s``. Only for a local Ollama
    (localhost) and when ``start_ollama`` is on."""
    if ollama_reachable():
        return True
    s = get_settings()
    if not s.start_ollama or not any(h in s.ollama_host for h in ("localhost", "127.0.0.1")):
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    for command in _ollama_programs():
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        except OSError:
            continue
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            time.sleep(1)
            if ollama_reachable():
                return True
    return False


def warm_up(model: str, system: str | None = None) -> float:
    """Load a model into memory. With ``system``, also process that system prompt so
    Ollama has it cached for the next real call. Returns seconds taken."""
    s = get_settings()
    started = time.perf_counter()
    try:
        client = _client(s.ollama_host, s.extract_timeout_s)
        if system:
            client.chat(model=model, messages=[{"role": "system", "content": system},
                                               {"role": "user", "content": "ready"}],
                        think=False, options=_options(num_predict=1), keep_alive=s.keep_alive)
        else:
            client.generate(model=model, prompt="", keep_alive=s.keep_alive)
    except ollama.ResponseError as error:
        raise LLMError(f"Could not load '{model}': {error}") from error
    except (httpx.ConnectError, ConnectionError) as error:
        raise LLMError(f"Cannot reach Ollama at {s.ollama_host}. Is it running?") from error
    return time.perf_counter() - started
