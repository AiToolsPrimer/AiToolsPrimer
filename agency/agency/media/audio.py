"""Voice (TTS), transcription (ASR) and music, each behind a tiny backend class
that runs the chosen local model and returns a file path.  All of them honour
``dry_run`` by producing silence so the whole pipeline can be rehearsed."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

import httpx

from agency.media.ffmpeg import FF
from agency.media.runner import MediaError, run_template
from agency.models.registry import ModelSpec

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, max_chars: int = 600) -> list[str]:
    """Split narration at sentence boundaries so each TTS call stays short and stable."""
    sentences = [s.strip() for s in SENTENCE_END.split(text.strip()) if s.strip()]
    chunks, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) + 1 > max_chars and cur:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


class TTS:
    def __init__(self, spec: ModelSpec, ff: FF, python: str = "python3", voice: str = "default", dry_run: bool = False, root: Path | None = None):
        self.spec, self.ff, self.python, self.voice, self.dry_run = spec, ff, python, voice, dry_run
        self.root = root or Path.cwd()

    def speak(self, text: str, out: Path, words_per_minute: int = 160) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.dry_run:
            seconds = max(1.0, len(text.split()) / words_per_minute * 60)
            return self.ff.silence(out, seconds)
        parts: list[Path] = []
        with tempfile.TemporaryDirectory() as td:
            for i, chunk in enumerate(chunk_text(text)):
                tf = Path(td) / f"chunk{i}.txt"
                tf.write_text(chunk)
                part = Path(td) / f"chunk{i}.wav"
                run_template(self.spec.command, {"python": self.python, "text": tf, "out": part, "voice": self.voice}, cwd=self.root)
                if not part.exists():
                    raise MediaError(f"TTS backend {self.spec.name} produced no audio for chunk {i}")
                parts.append(part)
            return self.ff.concat_audio(parts, out)


class ASR:
    def __init__(self, spec: ModelSpec, dry_run: bool = False):
        self.spec, self.dry_run = spec, dry_run

    def transcribe_srt(self, audio: Path, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        srt = out_dir / (audio.stem + ".srt")
        if self.dry_run:
            srt.write_text("1\n00:00:00,000 --> 00:00:03,000\n[dry run subtitles]\n")
            return srt
        run_template(self.spec.command, {"audio": audio, "model": self.spec.id, "out_dir": out_dir})
        if not srt.exists():
            cands = sorted(out_dir.glob("*.srt"), key=lambda p: p.stat().st_mtime)
            if not cands:
                raise MediaError(f"ASR backend {self.spec.name} wrote no .srt")
            srt = cands[-1]
        return srt


def srt_from_script(scenes: list[dict[str, Any]], out: Path) -> Path:
    """Subtitles straight from the narration timing, no model needed (used as the fallback)."""
    lines, t, n = [], 0.0, 1
    for sc in scenes:
        text, dur = sc["narration"], float(sc["seconds"])
        words = text.split()
        per = max(1, len(words) // max(1, int(dur // 4)))
        chunks = [" ".join(words[i : i + per]) for i in range(0, len(words), per)] or [text]
        step = dur / len(chunks)
        for c in chunks:
            lines.append(f"{n}\n{_ts(t)} --> {_ts(t + step)}\n{c}\n")
            t += step
            n += 1
    out.write_text("\n".join(lines))
    return out


def _ts(s: float) -> str:
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(sec):02d},{int((sec - int(sec)) * 1000):03d}"


class Music:
    """ACE-Step 1.5 through its local HTTP server. The request shape is configurable because the
    project exposes both a Gradio and a REST front; ``endpoint``/``payload`` live in agency.yaml."""

    def __init__(self, base_url: str, ff: FF, dry_run: bool = False, endpoint: str = "/generate", payload: dict[str, Any] | None = None, timeout: float = 1800):
        self.base_url, self.ff, self.dry_run, self.endpoint = base_url.rstrip("/"), ff, dry_run, endpoint
        self.payload = payload or {"prompt": "{prompt}", "lyrics": "[inst]", "duration": "{seconds}", "format": "wav"}
        self.client = httpx.Client(timeout=timeout)

    def generate(self, prompt: str, seconds: float, out: Path) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.dry_run:
            return self.ff.silence(out, seconds)
        body = {k: (v.replace("{prompt}", prompt).replace("{seconds}", str(int(seconds))) if isinstance(v, str) else v) for k, v in self.payload.items()}
        r = self.client.post(self.base_url + self.endpoint, json=body)
        if r.status_code >= 400:
            raise MediaError(f"ACE-Step returned {r.status_code}: {r.text[:300]}")
        ctype = r.headers.get("content-type", "")
        if ctype.startswith("audio/"):
            out.write_bytes(r.content)
            return out
        data = r.json()
        url = data.get("audio_url") or data.get("url") or (data.get("audio") or {}).get("url")
        if not url:
            raise MediaError(f"unexpected ACE-Step reply: {str(data)[:300]}")
        if url.startswith("/"):
            url = self.base_url + url
        out.write_bytes(self.client.get(url).content)
        return out
