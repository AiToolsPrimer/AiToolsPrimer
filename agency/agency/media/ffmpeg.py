"""Thin FFmpeg helpers used by the video assembler. Pure subprocess, no bindings."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


class FF:
    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"):
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe

    def _run(self, args: list[str]) -> None:
        proc = subprocess.run([self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args], capture_output=True, text=True)
        if proc.returncode != 0:
            raise FFmpegError(proc.stderr[-2000:])

    def duration(self, path: Path) -> float:
        proc = subprocess.run([self.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True)
        if proc.returncode != 0:
            raise FFmpegError(proc.stderr)
        return float(json.loads(proc.stdout)["format"]["duration"])

    def silence(self, out: Path, seconds: float) -> Path:
        self._run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{seconds:.3f}", "-c:a", "aac", str(out)])
        return out

    def concat_audio(self, parts: list[Path], out: Path) -> Path:
        lst = out.with_suffix(".txt")
        lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
        self._run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "aac", "-ar", "48000", str(out)])
        return out

    def concat_video(self, parts: list[Path], out: Path) -> Path:
        lst = out.with_suffix(".txt")
        lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
        self._run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])
        return out

    def normalize(self, src: Path, out: Path, width: int, height: int, fps: int, seconds: float | None = None) -> Path:
        """Re-encode a clip to the project format (same codec/size/fps so concat can stream-copy)."""
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps},format=yuv420p"
        args = ["-i", str(src)]
        if seconds:
            args += ["-t", f"{seconds:.3f}"]
        args += ["-vf", vf, "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)]
        self._run(args)
        return out

    def loop_to(self, src: Path, out: Path, seconds: float, width: int, height: int, fps: int) -> Path:
        """Loop a short generated clip (with a reverse bounce) until it covers ``seconds``."""
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps},format=yuv420p"
        self._run(["-stream_loop", "-1", "-i", str(src), "-t", f"{seconds:.3f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)])
        return out

    def ken_burns(self, image: Path, out: Path, seconds: float, width: int, height: int, fps: int, zoom_to: float = 1.12, direction: int = 0) -> Path:
        """Slow push-in / drift on a still image."""
        frames = max(int(seconds * fps), fps)
        pans = [
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
            f"x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)'",
            f"x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{frames}'",
            f"x='(iw-iw/zoom)*(1-on/{frames})':y='ih/2-(ih/zoom/2)'",
        ][direction % 4]
        vf = (
            f"scale={width*2}:{height*2}:force_original_aspect_ratio=increase,crop={width*2}:{height*2},"
            f"zoompan=z='min(1+({zoom_to}-1)*on/{frames},{zoom_to})':{pans}:d={frames}:s={width}x{height}:fps={fps},format=yuv420p"
        )
        self._run(["-loop", "1", "-i", str(image), "-t", f"{seconds:.3f}", "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)])
        return out

    def mux(self, video: Path, voice: Path, out: Path, music: Path | None = None, music_db: float = -18.0) -> Path:
        """Put the voiceover on the picture; mix a music bed under it with sidechain ducking."""
        if music:
            fc = (
                f"[2:a]volume={music_db}dB,aloop=loop=-1:size=2e9[m];"
                f"[m][1:a]sidechaincompress=threshold=0.05:ratio=8:attack=50:release=400[duck];"
                f"[1:a][duck]amix=inputs=2:duration=first:dropout_transition=2[a]"
            )
            self._run(["-i", str(video), "-i", str(voice), "-i", str(music), "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)])
        else:
            self._run(["-i", str(video), "-i", str(voice), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)])
        return out

    def burn_subtitles(self, video: Path, srt: Path, out: Path) -> Path:
        style = "FontName=Helvetica,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=2,Shadow=0,MarginV=60"
        path = str(srt).replace(":", "\\:").replace("'", "\\'")
        self._run(["-i", str(video), "-vf", f"subtitles='{path}':force_style='{style}'", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy", str(out)])
        return out

    def vertical_cut(self, video: Path, out: Path, start: float, seconds: float, width: int = 1080, height: int = 1920) -> Path:
        """Centre-crop a 16:9 master into a 9:16 short."""
        vf = f"crop=ih*9/16:ih,scale={width}:{height},format=yuv420p"
        self._run(["-ss", f"{start:.3f}", "-i", str(video), "-t", f"{seconds:.3f}", "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", str(out)])
        return out

    def thumbnail(self, video: Path, out: Path, at: float = 1.0) -> Path:
        self._run(["-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1", str(out)])
        return out

    def placeholder_clip(self, out: Path, seconds: float, width: int, height: int, fps: int, text: str = "") -> Path:
        """Used in dry runs and tests: a plain colour card so the pipeline can be exercised without models."""
        safe = text.replace("'", "").replace(":", " ")[:60]
        vf = f"drawtext=text='{safe}':fontcolor=white:fontsize=36:x=(w-text_w)/2:y=(h-text_h)/2" if text else "null"
        self._run(["-f", "lavfi", "-i", f"color=c=0x1f2937:s={width}x{height}:r={fps}", "-t", f"{seconds:.3f}", "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)])
        return out
