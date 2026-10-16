import json
import logging
import os
import re
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
        self.hf_model = os.getenv("HF_MODEL", "openai/whisper-small")
        self.hf_device = os.getenv("HF_DEVICE", "auto").lower()
        self.granite_window = float(os.getenv("GRANITE_WINDOW", "150"))
        self.granite_max_words = int(os.getenv("GRANITE_MAX_WORDS", "14"))
        self.granite_gap_break = float(os.getenv("GRANITE_GAP_BREAK", "0.8"))

        self.sub_font = os.getenv("SUB_FONT", "Arial")
        self.sub_fontsize = int(os.getenv("SUB_FONTSIZE", "28"))
        self.sub_color = os.getenv("SUB_COLOR", "white")
        self.sub_stroke_color = os.getenv("SUB_STROKE_COLOR", "black")
        self.sub_stroke_width = int(os.getenv("SUB_STROKE_WIDTH", "1"))
        self.sub_margin = int(os.getenv("SUB_MARGIN", "60"))

        self.processed_file = os.path.join(self.output_dir, ".captioner_processed")

        # Video encoding: av1/h264 (GPU) or libx264/libx265 (CPU)
        self.vcodec = os.getenv("VCODEC", "libx264").lower()
        self.v_preset = os.getenv("V_PRESET", "medium")
        # CRF for x264/x265; CQ/qp for NVENC/AV1 GPU encoders
        self.v_quality = os.getenv("V_QUALITY", "20")

        # Auto-set sensible defaults per codec if not overridden
        defaults = {
            "libx264":  {"preset": "medium",  "quality": "20", "mode": "crf"},
            "libx265":  {"preset": "medium",  "quality": "26", "mode": "crf"},
            "h264_nvenc":  {"preset": "p5",    "quality": "23", "mode": "cq"},
            "hevc_nvenc":  {"preset": "p5",    "quality": "28", "mode": "cq"},
            "av1_nvenc":   {"preset": "p5",    "quality": "35", "mode": "cq"},
        }
        d = defaults.get(self.vcodec)
        if d:
            if os.getenv("V_PRESET") is None: self.v_preset = d["preset"]
            if os.getenv("V_QUALITY") is None: self.v_quality = d["quality"]
            self._v_qmode = d["mode"]
        else:
            self._v_qmode = os.getenv("V_QMODE", "crf").lower()

    @property
    def use_granite(self) -> bool:
        return "granite-speech" in self.hf_model.lower()

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


def build_encode_args() -> list:
    """Codec-specific quality/preset args (crf for CPU, cq/qp for NVENC)."""
    c = CONFIG
    mode = getattr(c, "_v_qmode", "crf")
    preset_flag = {
        "h264_nvenc": "-preset", "hevc_nvenc": "-preset", "av1_nvenc": "-preset",
    }.get(c.vcodec, "-preset")
    quality_flag = {
        "crf": "-crf", "cq": "-cq", "qp": "-qp",
    }.get(mode, "-crf")
    return [
        "-c:v", c.vcodec,
        preset_flag, c.v_preset,
        quality_flag, c.v_quality,
    ]


def burn_subtitles(video_input: str, srt_input: str, video_output: str, info: dict) -> None:
    """Burn an .srt into the video, writing atomically to video_output."""
    work = tempfile.mkdtemp(prefix="captioner_burn_")
    root, ext = os.path.splitext(video_output)
    partial = root + ".partial" + ext
    try:
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
            vf += f":original_size={info['width']}x{info['height']}"
        vf += f":force_style='{style}'"

        cmd = [
            "ffmpeg", "-y", "-v", "error", "-i", video_input,
            "-vf", vf,
            *build_encode_args(),
            "-c:a", "aac", "-b:a", "192k",
            partial,
        ]
        try:
            _run(cmd, cwd=work)
            os.replace(partial, video_output)
        finally:
            if os.path.exists(partial):
                os.remove(partial)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# Transcription backends
# ---------------------------------------------------------------------------

_asr_pipeline = None


def _get_asr():
    global _asr_pipeline
    if _asr_pipeline is None:
        import torch
        from transformers import pipeline

        device = CONFIG.hf_device
        if device == "auto":
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        log.info("Loading HF model %r (device=%s)", CONFIG.hf_model, device)
        _asr_pipeline = pipeline(
            "automatic-speech-recognition",
            model=CONFIG.hf_model,
            device=device,
            token=os.getenv("HF_TOKEN", None)
        )
    return _asr_pipeline


def transcribe_local(audio_path: str) -> list:
    """Transcribe with a Hugging Face ASR pipeline (e.g. openai/whisper-small).
    Requires ffmpeg on PATH (already needed) to read the wav."""
    asr = _get_asr()
    result = asr(audio_path, return_timestamps=True)
    segments = []
    for chunk in result.get("chunks", []):
        start, end = chunk["timestamp"]
        if start is None:
            continue
        if end is None:  # final chunk can lack an end time
            end = start + 2.0
        segments.append({"start": start, "end": end, "text": chunk["text"]})
    return segments


# --- Granite Speech backend (ibm-granite/granite-speech-* models) -----------
#
# Granite Speech models are prompt-driven speech-LLMs; they don't work with
# the plain transformers ASR pipeline. We load the model + processor
# directly, ask for word-level timestamp tags ([T:N], centiseconds,
# mod 1000) and convert them into subtitle segments.

_granite_model = None

GRANITE_SYSTEM_PROMPT = (
    "Knowledge Cutoff Date: April 2024.\n"
    "Today's Date: December 19, 2024.\n"
    "You are Granite, developed by IBM. You are a AI moderator, developed by IBM."
    "You must translate any no English speech to English, otherwise you are to record precisely what is said."
)
GRANITE_TS_PROMPT = (
    "<|audio|> Timestamps: Transcribe the speech of players in a game for purposes of moderating them (this means it is especially important to transcribe any dog whistles, slurs, or other toxic content.)"
    "After each word, add a timestamp tag showing the end time in centiseconds, "
    "e.g. hello [T:45] world [T:82]"
)


def _get_granite():
    global _granite_model
    if _granite_model is None:
        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

        device = CONFIG.hf_device
        if device == "auto":
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        log.info("Loading Granite model %r (device=%s)", CONFIG.hf_model, device)
        processor = AutoProcessor.from_pretrained(
            CONFIG.hf_model, token=os.getenv("HF_TOKEN", None)
        )
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            CONFIG.hf_model, device_map=device,
            token=os.getenv("HF_TOKEN", None),
        )
        model.eval()
        _granite_model = (processor, model, device)
    return _granite_model


def _parse_granite_words(text: str) -> list:
    """Parse 'hello [T:45] world [T:82] ...' into [(word, end_seconds), ...],
    unwrapping the 10-second centisecond rollover (see model card)."""
    parts = re.split(r"\[T:(\d+)\]", text)
    words = []
    last_end = 0.0
    offset = 0.0
    for word, ts in zip(parts[::2], parts[1::2]):
        word = word.strip()
        if not word or word == "_":  # silence marker
            continue
        end = float(ts) / 100.0
        while end + offset < last_end:
            offset += 10.0
        last_end = end + offset
        words.append((word, last_end))
    return words


def _words_to_segments(words: list) -> list:
    """Group timestamped words into subtitle segments."""
    segments = []
    current = []
    start = None
    prev_end = 0.0

    def flush():
        nonlocal current, start
        if current:
            segments.append({
                "start": max(0.0, start),
                "end": current[-1][1],
                "text": " ".join(w for w, _ in current),
            })
        current = []
        start = None

    for word, end in words:
        if start is None:
            start = prev_end
        current.append((word, end))
        prev_end = end
        if (len(current) >= CONFIG.granite_max_words
                or end - start >= 6.0):
            flush()
    flush()
    return segments


def transcribe_granite(audio_path: str, duration: float) -> list:
    """Transcribe with a Granite Speech model (word timestamps via [T:N] tags).
    Audio is processed in windows because the timestamp mode is validated up
    to ~3.5 minutes of audio."""
    import soundfile as sf
    import torch

    processor, model, device = _get_granite()
    tokenizer = processor.tokenizer

    audio, sr = sf.read(audio_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    window_samples = int(CONFIG.granite_window * sr)
    segments = []
    for i in range(0, max(len(audio), 1), window_samples):
        chunk = audio[i:i + window_samples]
        if len(chunk) < sr // 2:  # skip sub-second trailing fragments
            break
        offset = i / sr

        chat = [
            {"role": "system", "content": GRANITE_SYSTEM_PROMPT},
            {"role": "user", "content": GRANITE_TS_PROMPT},
        ]
        prompt_text = tokenizer.apply_chat_template(
            chat, tokenize=False, add_generation_prompt=True
        )
        inputs = processor(
            prompt_text, chunk, device=device, return_tensors="pt"
        ).to(device)

        with torch.inference_mode():
            outputs = model.generate(
                **inputs, max_new_tokens=10000,
                do_sample=False, num_beams=1,
            )
        new_tokens = outputs[0, inputs["input_ids"].shape[-1]:]
        text = tokenizer.decode(
            new_tokens, add_special_tokens=False, skip_special_tokens=True
        )

        words = _parse_granite_words(text)
        if not words:
            # Prompt was ignored / no timestamps returned: fall back to a
            # single caption covering the window.
            if text.strip():
                segments.append({
                    "start": offset,
                    "end": offset + len(chunk) / sr,
                    "text": text.strip(),
                })
            continue
        segments.extend(_words_to_segments([
            (w, end + offset) for w, end in words
        ]))

    return segments


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
    if CONFIG.use_granite:
        return transcribe_granite(audio_path, duration)
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