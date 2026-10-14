# Medal Clip Captioner

Automatically captions your Medal gameplay clips. The script watches a folder (e.g. `C:\Medal\Clips\Garrys Mod`) for new videos, transcribes the audio with a **local Hugging Face Whisper model**, and burns the transcription into the video as styled subtitles — optionally saving the `.srt` alongside it.

## Features

- 🔁 **Directory watcher** — polls a folder and processes only new, unprocessed clips
- 🤗 **Local speech-to-text** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper) runs Hugging Face Whisper models fully offline (CPU or CUDA)
- 🌐 **Google fallback** — optional Google Web Speech API backend (no timestamps)
- 💬 **Real subtitles** — timestamped `.srt` files, text wrapping, styled burn-in via ffmpeg
- ⚙️ **`.env` configuration** — every path and option lives in one file
- 🛡️ **Robust** — per-file error handling, logging to console and `captioner.log`, skips clips with no audio

## Requirements

- Python 3.9+
- **FFmpeg** installed and on your `PATH` (required by MoviePy and for burning subtitles)

## Installation

```bash
git clone <your-repo-url>
cd medal-clip-captioner
pip install python-dotenv faster-whisper moviepy SpeechRecognition
```

For GPU acceleration, install with CUDA support per the [faster-whisper docs](https://github.com/SYSTRAN/faster-whisper):

```bash
pip install faster-whisper[gpu]
```

## Configuration

Create a `.env` file next to `captioner.py`:

```ini
# Directories
MONITOR_DIR=C:\Medal\Clips\Garrys Mod
OUTPUT_DIR=C:\Medal\Clips\Garrys Mod
VIDEO_EXTS=.mp4,.avi,.mov
POLL_INTERVAL=60

# Transcription backend: local (Whisper) or google
RECOGNIZER=local

# Local Whisper model (HF id or alias: tiny, base, small, medium, large-v3)
WHISPER_MODEL=small
WHISPER_DEVICE=cpu          # cpu or cuda
WHISPER_COMPUTE_TYPE=int8    # int8 for cpu, float16 for cuda

# Subtitle styling
SUB_FONT=Arial
SUB_FONTSIZE=28
SUB_COLOR=white
SUB_STROKE_COLOR=black
SUB_STROKE_WIDTH=1
SUB_MARGIN=60
```

| Variable | Default | Description |
|---|---|---|
| `MONITOR_DIR` | *(required)* | Folder watched for new clips |
| `OUTPUT_DIR` | `MONITOR_DIR` | Where captioned videos and `.srt` files are written |
| `VIDEO_EXTS` | `.mp4,.avi,.mov` | File extensions to process |
| `POLL_INTERVAL` | `60` | Seconds between scans |
| `RECOGNIZER` | `local` | `local` (Whisper) or `google` (Web Speech API) |
| `WHISPER_MODEL` | `small` | Model size or HF repo id — bigger = more accurate, slower |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8`/`int8_float16` for CPU, `float16` for GPU |
| `SUB_*` | see above | Font, size, colours, outline, and bottom margin of burned subtitles |

## Usage

```bash
python captioner.py
```

The script loops forever: scan the folder → caption any new clips → sleep `POLL_INTERVAL` seconds. Stop with `Ctrl+C`.

For each new clip it produces, in `OUTPUT_DIR`:

- `<name>_captioned.mp4` — the video with subtitles burned in (original audio preserved)
- `<name>.srt` — the standalone subtitle file

Processed files are recorded in `.captioner_processed`, so restarting the script never re-captions old clips. Delete that file to reprocess everything.

## Recommended models

| Model | Size | Speed (CPU) | Notes |
|---|---|---|---|
| `tiny` / `base` | 39–74 MB | ⚡ Fast | Good for loud, clear game comms |
| `small` | ~250 MB | Moderate | Best speed/accuracy balance |
| `medium` | ~750 MB | Slow | Noticeably better accuracy |
| `large-v3` | ~1.5 GB | Very slow on CPU | Best accuracy — use `cuda` |

## Troubleshooting

- **`FileNotFoundError: MONITOR_DIR`** — check the path in `.env` (quotes not needed).
- **`subtitles` filter errors** — ensure ffmpeg is on your `PATH`; on Windows the script escapes the drive-letter colon for you.
- **Captions out of sync** — VAD filtering and segment timestamps come from Whisper; try a larger model.
- **`google` backend returns nothing** — it requires internet and has no timestamps (one caption for the whole clip), which is why `local` is the default.
- **Reset processed list** — delete `.captioner_processed` in the output folder.

## License

MIT