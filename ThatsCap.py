import json
import logging
import os
import shutil
import subprocess
import tempfile
import time

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

CAPTION_SUFFIX = "_captioned"

class Config:
    def __init__(self) -> None:
        monitor = os.getenv("MONITOR_DIR", "").strip()
        output = os.getenv("OUTPUT_DIR", "").strip()
        self.monitor_dir = os.path.abspath(monitor) if monitor else ""
        self.output_dir = os.path.abspath(output) if output else self.monitor_dir

        self.video_exts = {
            ext.strip().lower()
            for ext in os.getenv("VIDEO_EXTS", ".mp4,.avi,.mov").split(",")
            if ext.strip()
        }
        self.poll_interval = float(os.getenv("POLL_INTERVAL", "60"))
        self.settle_seconds = float(os.getenv("SETTLE_SECONDS", "5"))

        # Transcription backend
        self.recognizer = os.getenv("RECOGNIZER", "local").lower()
        self.whisper_model = os.getenv("WHISPER_MODEL", "small")
        self.whisper_device = os.getenv("WHISPER_DEVICE", "cpu")
        self.whisper_compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

        self.sub_font = os.getenv("SUB_FONT", "Arial")
        self.sub_fontsize = int(os.getenv("SUB_FONTSIZE", "28"))
        self.sub_color = os.getenv("SUB_COLOR", "white")
        self.sub_stroke_color = os.getenv("SUB_STROKE_COLOR", "black")
        self.sub_stroke_width = int(os.getenv("SUB_STROKE_WIDTH", "1"))
        self.sub_margin = int(os.getenv("SUB_MARGIN", "60"))

        self.processed_file = os.path.join(self.output_dir, ".captioner_processed")

    def validate(self) -> None:
        if not self.monitor_dir:
            raise ValueError("MONITOR_DIR is not set")
        if not os.path.isdir(self.monitor_dir):
            raise FileNotFoundError(
                f"MONITOR_DIR does not exist: {self.monitor_dir}"
            )
        os.makedirs(self.output_dir, exist_ok=True)
        for tool in ("ffmpeg", "ffprobe"):
            if shutil.which(tool) is None:
                raise FileNotFoundError(f"{tool} was not found on PATH")


CONFIG = Config()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("captioner.log")],
)
log = logging.getLogger("captioner")


# ---------------------------------------------------------------------------
# Subtitle handling
# ---------------------------------------------------------------------------


def _format_srt_timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: list, path: str) -> str:
    """Write whisper-style segments (start/end/text) to an .srt file."""
    blocks = []
    index = 1
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        blocks.append(
            f"{index}\n"
            f"{_format_srt_timestamp(seg['start'])} --> "
            f"{_format_srt_timestamp(seg['end'])}\n"
            f"{text}\n"
        )
        index += 1

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks))
    return path


_NAMED_COLORS = {
    "white": "FFFFFF",
    "black": "000000",
    "red": "FF0000",
    "green": "00FF00",
    "blue": "0000FF",
    "yellow": "FFFF00",
    "cyan": "00FFFF",
    "magenta": "FF00FF",
    "orange": "FFA500",
    "gray": "808080",
    "grey": "808080",
}


def ass_color(value: str, default: str = "FFFFFF") -> str:
    """Convert 'white' / '#RRGGBB' into libass '&H00BBGGRR' format."""
    v = value.strip().lower()
    if v.startswith("#"):
        v = v[1:]
    rgb = _NAMED_COLORS.get(v, v).upper()
    if len(rgb) != 6 or any(c not in "0123456789ABCDEF" for c in rgb):
        log.warning("Unrecognised colour %r, using default", value)
        rgb = default
    r, g, b = rgb[0:2], rgb[2:4], rgb[4:6]
    return f"&H00{b}{g}{r}"


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------


def _run(cmd: list, cwd: str = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {result.stderr.strip()[-800:]}")
    return result


def probe_video(path: str) -> dict:
    out = _run([
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,width,height:format=duration",
        "-of", "json", path,
    ]).stdout
    data = json.loads(out)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": video.get("width"),
        "height": video.get("height"),
        "duration": float(data.get("format", {}).get("duration") or 0),
    }


def extract_audio(video_path: str, wav_path: str) -> None:
    _run([
        "ffmpeg", "-y", "-v", "error", "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav_path,
    ])


def burn_subtitles(video_input: str, srt_input: str, video_output: str, info: dict) -> None:
    """Burn an .srt into the video, writing atomically to video_output."""
    work = tempfile.mkdtemp(prefix="captioner_burn_")
    root, ext = os.path.splitext(video_output)
    partial = root + ".partial" + ext
    try:
        # Copy the srt to a plain relative name: avoids Windows drive-letter /
        # backslash escaping problems inside the ffmpeg filter string.
        shutil.copy(srt_input, os.path.join(work, "subs.srt"))

        style = (
            f"Fontname={CONFIG.sub_font},Fontsize={CONFIG.sub_fontsize},"
            f"PrimaryColour={ass_color(CONFIG.sub_color)},"
            f"OutlineColour={ass_color(CONFIG.sub_stroke_color, '000000')},"
            f"BorderStyle=1,Outline={CONFIG.sub_stroke_width},Shadow=0,"
            f"Alignment=2,MarginV={CONFIG.sub_margin}"
        )
        vf = "subtitles=subs.srt"
        if info.get("width") and info.get("height"):
            # Makes Fontsize/MarginV be in real video pixels
            vf += f":original_size={info['width']}x{info['height']}"
        vf += f":force_style='{style}'"

        try:
            # We dynamically inject your existing 'vf' string and mix all audio tracks
            filter_complex_str = f"[0:v:0]{vf}[v];[0:a]amix=inputs=2:duration=longest[a]"

            _run([
                "ffmpeg", "-y", "-v", "error", "-i", video_input,
                "-filter_complex", filter_complex_str,
                "-map", "[v]",
                "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k",  # Re-encoding is required to merge audio
                partial,
            ], cwd=work)
            os.replace(partial, video_output)
        finally:
            if os.path.exists(partial):
                os.remove(partial)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# Transcription backends
# ---------------------------------------------------------------------------

_whisper_model = None
_whisper_device = None


def _load_whisper(device: str, compute_type: str):
    from faster_whisper import WhisperModel

    log.info(
        "Loading Whisper model %r (device=%s, compute=%s)",
        CONFIG.whisper_model, device, compute_type,
    )
    return WhisperModel(CONFIG.whisper_model, device=device, compute_type=compute_type)


def _get_whisper():
    global _whisper_model, _whisper_device
    if _whisper_model is None:
        try:
            _whisper_device = CONFIG.whisper_device
            _whisper_model = _load_whisper(_whisper_device, CONFIG.whisper_compute_type)
        except Exception as exc:
            if CONFIG.whisper_device == "cpu":
                raise
            log.warning("Could not load Whisper on %s (%s), falling back to CPU",
                        CONFIG.whisper_device, exc)
            _whisper_device = "cpu"
            _whisper_model = _load_whisper("cpu", "int8")
    return _whisper_model


def _whisper_transcribe(audio_path: str) -> list:
    model = _get_whisper()
    segments_iter, info = model.transcribe(
        audio_path, word_timestamps=False, vad_filter=True
    )
    log.info("Detected language: %s (prob %.2f)",
             info.language, info.language_probability)
    # The iterator is lazy; CUDA errors can surface while consuming it
    return [{"start": s.start, "end": s.end, "text": s.text} for s in segments_iter]


def transcribe_local(audio_path: str) -> list:
    """Transcribe with a local Whisper model via faster-whisper."""
    global _whisper_model, _whisper_device
    try:
        return _whisper_transcribe(audio_path)
    except RuntimeError as exc:
        if _whisper_device == "cpu":
            raise
        log.warning("Whisper failed on %s (%s), retrying on CPU", _whisper_device, exc)
        _whisper_device = "cpu"
        _whisper_model = _load_whisper("cpu", "int8")
        return _whisper_transcribe(audio_path)


def transcribe_google(audio_path: str, duration: float) -> list:
    """Fallback: Google Web Speech API. No timestamps, so one caption for the
    whole clip (the API also only handles short clips)."""
    import speech_recognition as sr

    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_path) as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.3)
        audio_data = recognizer.record(source)
    try:
        text = recognizer.recognize_google(audio_data)
    except sr.UnknownValueError:
        return []
    except sr.RequestError as exc:
        raise RuntimeError(f"Google Speech API error: {exc}") from exc
    return [{"start": 0.0, "end": max(duration, 0.5), "text": text}]


def transcribe_audio(audio_path: str, duration: float) -> list:
    if CONFIG.recognizer == "google":
        return transcribe_google(audio_path, duration)
    return transcribe_local(audio_path)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def output_path_for(video_path: str) -> str:
    """Where the captioned version of video_path lives (mirrors subfolders)."""
    rel_dir, name = os.path.split(os.path.relpath(video_path, CONFIG.monitor_dir))
    stem, ext = os.path.splitext(name)
    return os.path.join(CONFIG.output_dir, rel_dir, stem + CAPTION_SUFFIX + ext)


def is_caption_output(filename: str) -> bool:
    return os.path.splitext(filename)[0].endswith(CAPTION_SUFFIX)


# ---------------------------------------------------------------------------
# Video processing
# ---------------------------------------------------------------------------


def process_video(video_path: str) -> bool:
    """Caption one video. Returns False if there was nothing to caption
    (no audio / no speech), True if a captioned file was written."""
    log.info("Processing %s", video_path)
    info = probe_video(video_path)
    if not info["has_audio"]:
        log.warning("No audio track in %s, skipping.", video_path)
        return False

    output_path = output_path_for(video_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    tmpdir = tempfile.mkdtemp(prefix="captioner_")
    try:
        wav_path = os.path.join(tmpdir, "audio.wav")
        extract_audio(video_path, wav_path)
        segments = transcribe_audio(wav_path, info["duration"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if not segments:
        log.warning("No speech detected in %s, skipping.", video_path)
        return False

    srt_path = write_srt(segments, os.path.splitext(output_path)[0] + ".srt")
    log.info("Burning subtitles -> %s", os.path.basename(output_path))
    burn_subtitles(video_path, srt_path, output_path, info)
    log.info("Done: %s", output_path)
    return True


# ---------------------------------------------------------------------------
# Directory monitoring
# ---------------------------------------------------------------------------

# Videos that failed this session; retried on next restart, not every poll
_failed = set()


def load_processed() -> set:
    if not os.path.exists(CONFIG.processed_file):
        return set()
    with open(CONFIG.processed_file, "r", encoding="utf-8") as fh:
        return {line.strip() for line in fh if line.strip()}


def mark_processed(path: str) -> None:
    with open(CONFIG.processed_file, "a", encoding="utf-8") as fh:
        fh.write(path + "\n")


def find_uncaptioned() -> list:
    """Every video under MONITOR_DIR (recursively) with no captioned version
    in the output dir yet. This covers new clips and old backlog alike."""
    processed = load_processed()
    out_root = os.path.normcase(CONFIG.output_dir)
    monitor_root = os.path.normcase(CONFIG.monitor_dir)
    now = time.time()
    pending = []

    for root, dirs, files in os.walk(CONFIG.monitor_dir):
        # Don't descend into the output folder when it sits inside the monitor
        # folder (but it's fine if they're the same folder)
        if out_root != monitor_root:
            dirs[:] = [
                d for d in dirs
                if os.path.normcase(os.path.join(root, d)) != out_root
            ]

        for name in sorted(files):
            stem, ext = os.path.splitext(name)
            if ext.lower() not in CONFIG.video_exts:
                continue
            if is_caption_output(name) or ".partial" in stem:
                continue

            path = os.path.join(root, name)
            if path in processed or path in _failed:
                continue
            if os.path.exists(output_path_for(path)):
                continue
            try:
                if now - os.path.getmtime(path) < CONFIG.settle_seconds:
                    continue  # probably still being written
            except OSError:
                continue
            pending.append(path)

    return pending


def scan_directory() -> None:
    pending = find_uncaptioned()
    if pending:
        log.info("%d video(s) without a captioned version", len(pending))

    for path in pending:
        try:
            if not process_video(path):
                mark_processed(path)  # nothing to caption; don't retry
        except Exception:
            _failed.add(path)
            log.exception("Failed to process %s", path)


def main() -> None:
    CONFIG.validate()
    log.info(
        "Monitoring %s -> %s (every %ss, backend=%s)",
        CONFIG.monitor_dir, CONFIG.output_dir,
        CONFIG.poll_interval, CONFIG.recognizer,
    )
    try:
        while True:
            scan_directory()
            time.sleep(CONFIG.poll_interval)
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()