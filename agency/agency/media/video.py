"""Long-form video assembly.

No generative model makes a four-minute video in one pass, and on a Mac the
sensible unit is a clip of a few seconds.  So a video is *planned* as scenes,
each scene gets a narration line, a visual (a generated clip looped to the
narration length, or a generated still with slow camera motion, or a presenter
shot), and the pieces are assembled with FFmpeg: picture + voice + ducked music
bed + subtitles.  The same master is cut into vertical shorts.
"""
from __future__ import annotations

import random
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agency.media.audio import ASR, TTS, Music, srt_from_script
from agency.media.ffmpeg import FF
from agency.media.images import Images
from agency.media.runner import ComfyUI, MediaError
from agency.models.host import ModelHost
from agency.models.registry import ModelSpec
from agency.settings import VideoDefaults

WORDS_PER_SECOND = 2.6  # ~155 wpm narration


@dataclass
class Scene:
    narration: str
    visual_prompt: str
    mode: str = "image_motion"          # generated | image_motion | presenter
    seconds: float = 0.0                # filled from narration length when 0
    on_screen_text: str = ""

    def estimate(self) -> float:
        return max(3.0, round(len(self.narration.split()) / WORDS_PER_SECOND + 0.6, 1))


@dataclass
class VideoPlan:
    title: str
    scenes: list[Scene]
    music_prompt: str = "calm minimal electronic bed, no vocals, steady, unobtrusive"
    hook_seconds: float = 0.0
    shorts: list[tuple[float, float]] = field(default_factory=list)   # (start, length) cut points

    def total(self) -> float:
        return sum(s.seconds or s.estimate() for s in self.scenes)

    @classmethod
    def from_json(cls, data: dict[str, Any], max_seconds: int, default_mode: str = "mixed") -> "VideoPlan":
        scenes = []
        for i, s in enumerate(data.get("scenes", [])):
            mode = s.get("mode") or ("generated" if default_mode == "mixed" and i % 3 == 0 else "image_motion" if default_mode == "mixed" else default_mode)
            sc = Scene(narration=s["narration"].strip(), visual_prompt=s.get("visual_prompt", "").strip() or s["narration"][:200], mode=mode, on_screen_text=s.get("on_screen_text", ""))
            sc.seconds = float(s.get("seconds") or sc.estimate())
            scenes.append(sc)
        plan = cls(title=data.get("title", "Untitled"), scenes=scenes, music_prompt=data.get("music_prompt") or cls.music_prompt)
        plan.clamp(max_seconds)
        return plan

    def clamp(self, max_seconds: int) -> None:
        """Drop trailing scenes until the plan fits the limit (the director is told to aim under it)."""
        while self.scenes and self.total() > max_seconds:
            if len(self.scenes) == 1:
                self.scenes[0].seconds = float(max_seconds)
                break
            self.scenes.pop()


def _round32(n: int) -> int:
    return max(32, int(round(n / 32)) * 32)


class VideoAssembler:
    def __init__(
        self,
        *,
        ff: FF,
        tts: TTS,
        asr: ASR | None,
        music: Music | None,
        images: Images,
        video_spec: ModelSpec,
        avatar_spec: ModelSpec | None,
        comfy: ComfyUI | None,
        workflows_dir: Path,
        defaults: VideoDefaults,
        host: ModelHost | None = None,
        python: str = "python3",
        dry_run: bool = False,
        video_command: str = "",
        presenter_image: Path | None = None,
        progress: Callable[[str], None] | None = None,
    ):
        self.ff, self.tts, self.asr, self.music, self.images = ff, tts, asr, music, images
        self.video_spec, self.avatar_spec, self.comfy, self.workflows_dir = video_spec, avatar_spec, comfy, workflows_dir
        self.d, self.python, self.dry_run = defaults, python, dry_run
        self.host = host
        self.video_command = video_command or video_spec.command
        self.presenter_image = presenter_image
        self.progress = progress or (lambda msg: None)

    # ------------------------------------------------------------------ pieces
    def generate_clip(self, prompt: str, out: Path, seconds: float, seed: int | None = None) -> Path:
        seconds = min(seconds, self.d.clip_seconds)
        frames = int(seconds * self.d.fps) // 8 * 8 + 1   # LTX wants 8k+1 frames
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.dry_run:
            return self.ff.placeholder_clip(out, seconds, self.d.width, self.d.height, self.d.fps, prompt)
        if self.comfy and (self.workflows_dir / "video.json").exists():
            if self.host:
                self.host.release()
            wf = ComfyUI.fill(self.workflows_dir / "video.json", {"prompt": prompt, "seed": seed or random.randint(1, 2**31), "width": self.d.width, "height": self.d.height, "frames": frames, "fps": self.d.fps})
            files = self.comfy.run(wf, out.parent)
            files[0].replace(out)
            return out
        if not self.host:
            raise MediaError("video generation needs the model host")
        w32, h32 = _round32(self.d.width), _round32(self.d.height)   # LTX wants sides divisible by 32; normalize() crops back
        self.host.run_job(self.video_spec, self.video_command, {"prompt": prompt, "out": out, "width": w32, "height": h32, "frames": frames, "fps": self.d.fps, "seed": seed or random.randint(1, 2**31)})
        if not out.exists():
            raise MediaError("video backend produced no file")
        return out

    def presenter_clip(self, audio: Path, out: Path, seconds: float) -> Path:
        if self.dry_run or not self.avatar_spec or not self.presenter_image or not self.comfy or not (self.workflows_dir / "avatar.json").exists():
            return self.ff.placeholder_clip(out, seconds, self.d.width, self.d.height, self.d.fps, "presenter")
        if self.host:
            self.host.release()
        wf = ComfyUI.fill(self.workflows_dir / "avatar.json", {"image": str(self.presenter_image.resolve()), "audio": str(audio.resolve()), "width": self.d.width, "height": self.d.height, "fps": self.d.fps})
        files = self.comfy.run(wf, out.parent)
        files[0].replace(out)
        return out

    # ------------------------------------------------------------------ assembly
    def build(self, plan: VideoPlan, workdir: Path, with_shorts: bool = True) -> dict[str, Any]:
        workdir.mkdir(parents=True, exist_ok=True)
        plan.clamp(self.d.max_seconds)
        W, H, FPS = self.d.width, self.d.height, self.d.fps
        voice_parts, video_parts = [], []
        for i, sc in enumerate(plan.scenes):
            self.progress(f"scene {i+1}/{len(plan.scenes)}: voice")
            voice = self.tts.speak(sc.narration, workdir / f"voice_{i:02d}.m4a")
            real = self.ff.duration(voice) + 0.4
            sc.seconds = max(sc.seconds, real)
            # pad the voice to the scene length so picture and sound stay aligned
            if real < sc.seconds:
                pad = self.ff.silence(workdir / f"pad_{i:02d}.m4a", sc.seconds - real)
                voice = self.ff.concat_audio([voice, pad], workdir / f"voice_{i:02d}_padded.m4a")
            voice_parts.append(voice)
            self.progress(f"scene {i+1}/{len(plan.scenes)}: picture ({sc.mode})")
            raw = workdir / f"raw_{i:02d}.mp4"
            if sc.mode == "generated":
                clip = self.generate_clip(sc.visual_prompt, raw, sc.seconds)
                vid = self.ff.loop_to(clip, workdir / f"scene_{i:02d}.mp4", sc.seconds, W, H, FPS)
            elif sc.mode == "presenter":
                clip = self.presenter_clip(voice, raw, sc.seconds)
                vid = self.ff.normalize(clip, workdir / f"scene_{i:02d}.mp4", W, H, FPS, sc.seconds)
            else:
                still = self.images.generate(sc.visual_prompt, workdir / f"still_{i:02d}.png", size="landscape")
                vid = self.ff.ken_burns(still, workdir / f"scene_{i:02d}.mp4", sc.seconds, W, H, FPS, direction=i)
            video_parts.append(vid)
        self.progress("assembling")
        picture = self.ff.concat_video(video_parts, workdir / "picture.mp4")
        voice = self.ff.concat_audio(voice_parts, workdir / "voice.m4a")
        total = self.ff.duration(voice)
        music = self.music.generate(plan.music_prompt, total + 2, workdir / "music.wav") if self.music else None
        master = self.ff.mux(picture, voice, workdir / "master_nosub.mp4", music=music, music_db=self.d.music_db)
        srt = self.asr.transcribe_srt(voice, workdir) if self.asr else srt_from_script([{"narration": s.narration, "seconds": s.seconds} for s in plan.scenes], workdir / "voice.srt")
        final = workdir / "final.mp4"
        if self.d.subtitles == "burned":
            self.ff.burn_subtitles(master, srt, final)
        else:
            shutil.copy(master, final)
        thumb = self.ff.thumbnail(final, workdir / "thumbnail.png", min(2.0, total / 2))
        result: dict[str, Any] = {"video": final, "srt": srt, "thumbnail": thumb, "seconds": round(total, 1), "scenes": len(plan.scenes)}
        if with_shorts:
            result["shorts"] = self.cut_shorts(final, plan, workdir)
        return result

    def cut_shorts(self, master: Path, plan: VideoPlan, workdir: Path) -> list[Path]:
        """One short from the hook (first scenes) and one from the strongest middle section."""
        total = self.ff.duration(master)
        length = min(self.d.shorts_seconds, total)
        cuts = [(0.0, length)]
        if total > length * 2.5:
            # start at a scene boundary near the middle
            t, mid = 0.0, total / 2
            for sc in plan.scenes:
                if t + sc.seconds > mid:
                    break
                t += sc.seconds
            cuts.append((min(t, total - length), length))
        out = []
        for n, (start, secs) in enumerate(cuts):
            out.append(self.ff.vertical_cut(master, workdir / f"short_{n}.mp4", start, secs))
        return out
