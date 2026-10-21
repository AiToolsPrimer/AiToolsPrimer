"""Voice (TTS), transcription (ASR) and music, each run through the ModelHost so
that nothing else is resident while they work.  All honour ``dry_run`` by producing
silence so the whole pipeline can be rehearsed."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

import httpx

from agency.media.ffmpeg import FF
from agency.media.runner import MediaError
from agency.models.host import ModelHost
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
    def __init__(self, spec: ModelSpec, host: ModelHost, ff: FF, voice: str = "default", dry_run: bool = False, root: Path | None = None, fallbacks: tuple[ModelSpec, ...] = ()):
        self.spec, self.host, self.ff, self.voice, self.dry_run = spec, host, ff, voice, dry_run
        self.root = root or Path.cwd()
        self.fallbacks = fallbacks

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
                self._speak_chunk(tf, part)
                parts.append(part)
            return self.ff.concat_audio(parts, out)

    def _speak_chunk(self, text_file: Path, part: Path) -> None:
        last: Exception | None = None
        for spec in (self.spec, *self.fallbacks):
            try:
                self.host.run_job(spec, spec.command, {"text": text_file, "out": part, "voice": self.voice}, cwd=self.root)
                if part.exists():
                    return
                last = MediaError(f"{spec.name} produced no audio")
            except Exception as e:  # noqa: BLE001
                last = e
        raise MediaError(f"every TTS backend failed: {last}")


class ASR:
    def __init__(self, spec: ModelSpec, host: ModelHost, dry_run: bool = False):
        self.spec, self.host, self.dry_run = spec, host, dry_run

    def transcribe_srt(self, audio: Path, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        srt = out_dir / (audio.stem + ".srt")
        if self.dry_run:
            srt.write_text("1\n00:00:00,000 --> 00:00:03,000\n[dry run subtitles]\n")
            return srt
        self.host.run_job(self.spec, self.spec.command, {"audio": audio, "out_dir": out_dir})
        if not srt.exists():
            cands = sorted(out_dir.glob("*.srt"), key=lambda p: p.stat().st_mtime)
            if not cands:
                raise MediaError(f"ASR backend {self.spec.name} wrote no .srt")
            srt = cands[-1]
        return srt


def srt_from_script(scenes: list[dict[str, Any]], out: Path) -> Path:
    """Subtitles straight from the narration timing, no model needed (exact, since we wrote the script)."""
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
    """ACE-Step 1.5 through its local HTTP server, started by the host on demand. The request
    shape is configurable because the project exposes both a Gradio and a REST front."""

    def __init__(self, spec: ModelSpec, host: ModelHost, ff: FF, dry_run: bool = False, endpoint: str = "/generate", payload: dict[str, Any] | None = None, timeout: float = 1800):
        self.spec, self.host, self.ff, self.dry_run, self.endpoint = spec, host, ff, dry_run, endpoint
        self.payload = payload or {"prompt": "{prompt}", "lyrics": "[inst]", "duration": "{seconds}", "format": "wav"}
        self.timeout = timeout

    def generate(self, prompt: str, seconds: float, out: Path) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.dry_run:
            return self.ff.silence(out, seconds)
        ep = self.host.activate(self.spec)
        body = {k: (v.replace("{prompt}", prompt).replace("{seconds}", str(int(seconds))) if isinstance(v, str) else v) for k, v in self.payload.items()}
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(ep.base_url + self.endpoint, json=body)
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
                url = ep.base_url + url
            out.write_bytes(client.get(url).content)
        return out
