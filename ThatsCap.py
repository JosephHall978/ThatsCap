import logging
import os
import time
import ffmpeg

from dotenv import load_dotenv

import tempfile
from moviepy import VideoFileClip, TextClip

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()


class Config:
    """All settings, loaded from environment / .env with sensible defaults."""

    def __init__(self) -> None:
        self.monitor_dir = os.getenv("MONITOR_DIR", "").strip()
        self.output_dir = os.getenv("OUTPUT_DIR", str(self.monitor_dir)).strip()
        self.video_exts = {
            ext.strip().lower()
            for ext in os.getenv("VIDEO_EXTS", ".mp4,.avi,.mov").split(",")
            if ext.strip()
        }
        self.poll_interval = float(os.getenv("POLL_INTERVAL", "60"))

        # Transcription backend
        self.recognizer = os.getenv("RECOGNIZER", "local").lower()
        self.whisper_model = os.getenv("WHISPER_MODEL", "small")
        self.whisper_device = os.getenv("WHISPER_DEVICE", "cpu")
        self.whisper_compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

        # Subtitle styling
        self.sub_font = os.getenv("SUB_FONT", "Arial")
        self.sub_fontsize = int(os.getenv("SUB_FONTSIZE", "28"))
        self.sub_color = os.getenv("SUB_COLOR", "white")
        self.sub_stroke_color = os.getenv("SUB_STROKE_COLOR", "black")
        self.sub_stroke_width = int(os.getenv("SUB_STROKE_WIDTH", "1"))
        self.sub_margin = int(os.getenv("SUB_MARGIN", "60"))

        # Tracks already-processed videos (one path per line)
        self.processed_file = self.output_dir + ".captioner_processed"

    def validate(self) -> None:
        if not self.monitor_dir:
            raise FileNotFoundError(
                f"MONITOR_DIR does is not set: {self.monitor_dir}"
            )
        if not os.path.isdir(self.monitor_dir):
            os.mkdir(self.output_dir)


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
    lines = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(
            f"{_format_srt_timestamp(seg['start'])} --> "
            f"{_format_srt_timestamp(seg['end'])}"
        )
        text = seg["text"].strip()
        lines.append(text)
        lines.append("")

    with open(path, "w+", encoding="utf-8") as f:
        f.writelines(lines)

    return path


def wrap_text(text: str, max_chars: int = 42) -> list[str]:
    """Split long text into subtitle-sized chunks of <= 2 lines."""
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    # Pair lines up so each caption is at most 2 lines
    return [lines[i : i + 2] for i in range(0, len(lines), 2)]


def build_clip_texts(segments: list) -> list:
    """Turn raw segments into styled, chunked caption entries."""
    entries = []
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        chunks = wrap_text(text)
        span = max(seg["end"] - seg["start"], 0.1) / len(chunks)
        for i, chunk in enumerate(chunks):
            start = seg["start"] + i * span
            end = min(start + span, seg["end"]) if i < len(chunks) - 1 else seg["end"]
            entries.append({"start": start, "end": max(end, start + 0.5), "text": "\n".join(chunk)})
    return entries


# ---------------------------------------------------------------------------
# Transcription backends
# ---------------------------------------------------------------------------

_whisper_model = None


def transcribe_local(audio_path: str) -> list:
    """Transcribe with a local Hugging Face Whisper model via faster-whisper."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        log.info(
            "Loading Whisper model %r (device=%s, compute=%s)",
            CONFIG.whisper_model,
            CONFIG.whisper_device,
            CONFIG.whisper_compute_type,
        )
        _whisper_model = WhisperModel(
            CONFIG.whisper_model,
            device=CONFIG.whisper_device,
            compute_type=CONFIG.whisper_compute_type,
        )

    segments_iter, info = _whisper_model.transcribe(
        audio_path, word_timestamps=False, vad_filter=True
    )
    log.info(
        "Detected language: %s (prob %.2f)", info.language, info.language_probability
    )
    return [{"start": s.start, "end": s.end, "text": s.text} for s in segments_iter]


def transcribe_google(audio_path: str) -> list:
    """Fallback: Google Web Speech API. No timestamps, so use one caption."""
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
    return [{"start": 0.0, "end": None, "text": text}]


def transcribe_audio(audio_path: str, duration: float) -> list:
    if CONFIG.recognizer == "google":
        return transcribe_google(audio_path)
    return transcribe_local(audio_path)


# ---------------------------------------------------------------------------
# Video processing
# ---------------------------------------------------------------------------
def burn_subtitles(video_input, srt_input, video_output):
    try:
        stream = ffmpeg.input(video_input)
        video = stream.video.filter('subtitles', srt_input, force_style='Fontname=Arial,Fontsize=16')
        audio = stream.audio
        output = ffmpeg.output(video, audio, video_output, vcodec='libx264', acodec='copy')
        ffmpeg.run(output, overwrite_output=True)
        log.info("Burning subtitles -> %s", video_output.name)
    except ffmpeg.Error as e:
        log.warning("Could not burn subtitles -> %s", video_output.name)


def process_video(video_path: str) -> None:
    log.info("Processing %s", video_path)
    with VideoFileClip(video_path) as video:
        if video.audio is None:
            log.warning("No audio track in %s, skipping.", video_path)
            return
        duration = video.duration
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio_path = os.path.basename(tmp)
        try:
            video.audio.write_audiofile(
                str(audio_path), logger=None, codec="pcm_s16le"
            )
            segments = transcribe_audio(audio_path, duration)
        finally:
            audio_path.unlink(missing_ok=True)

    if not segments:
        log.warning("No speech detected in %s, skipping.", video_path)
        return

    base = os.path.dirname(video_path)
    srt_path = write_srt(segments, CONFIG.output_dir / f"{base}.srt")
    output_path = CONFIG.output_dir / f"{base}_captioned{os.path.basename(video_path)}"
    burn_subtitles(video_path, srt_path, output_path)
    log.info("Done: %s", output_path.name)


# ---------------------------------------------------------------------------
# Directory monitoring
# ---------------------------------------------------------------------------


def load_processed() -> set:
    if os.path.exists(CONFIG.processed_file):
        return {
            line.strip()
            for line in CONFIG.processed_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    return set()


def mark_processed(path: str) -> None:
    with CONFIG.processed_file.open("a", encoding="utf-8") as fh:
        fh.write(path + "\n")


def scan_directory() -> None:
    processed = load_processed()
    for entry, dirs, names in os.walk(CONFIG.monitor_dir):
        entry = os.sep.join(entry)
        if (
            os.path.isfile(entry)
            and os.path.basename(entry).lower() in CONFIG.video_exts
            and str(entry) not in processed
        ):
            try:
                process_video(entry)
                mark_processed(str(entry))
            except Exception:
                log.exception("Failed to process %s", names)


def main() -> None:
    CONFIG.validate()
    log.info(
        "Monitoring %s (every %ss, backend=%s)",
        CONFIG.monitor_dir,
        CONFIG.poll_interval,
        CONFIG.recognizer,
    )
    while True:
        scan_directory()
        time.sleep(CONFIG.poll_interval)


if __name__ == "__main__":
    main()