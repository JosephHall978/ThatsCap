# ThatsCap

Automatically captions your gameplay clips. The script watches a folder (e.g. `C:\Medal\Clips\Garrys Mod`) for new videos, transcribes the audio with a **local Hugging Face Whisper model**, and burns the transcription into the video as styled subtitles — saving the `.srt` alongside it.

## Features

- 🔁 **Recursive directory watcher** — polls a folder tree and processes only clips that don't have a captioned version yet (new clips *and* old backlog), mirroring subfolders in the output
- 🤗 **Local speech-to-text** — a Hugging Face `transformers` ASR pipeline (e.g. `openai/whisper-small`) runs fully offline on CPU or CUDA
- 🌐 **Google fallback** — optional Google Web Speech API backend (no timestamps)
- 💬 **Real subtitles** — timestamped `.srt` files, styled burn-in via ffmpeg's `subtitles` filter
- 🎛️ **Configurable encoding** — CPU (`libx264`/`libx265`) or NVIDIA GPU (`h264_nvenc`, `hevc_nvenc`, `av1_nvenc`) with sensible per-codec defaults
- ⚙️ **`.env` configuration** — every path and option lives in one file
- 🛡️ **Robust** — atomic output writes (no half-finished files), per-file error handling, logging to console and `captioner.log`, skips clips with no audio

## Requirements

- Python 3.9+
- **FFmpeg** installed and on your `PATH` (`ffmpeg` and `ffprobe` are both required)

## Installation

```bash
git clone https://github.com/JosephHall978/ThatsCap.git
cd ThatsCap
pip install -r requirements.txt
```

For GPU acceleration, install a CUDA-enabled PyTorch build per the [PyTorch docs](https://pytorch.org/get-started/locally/).
```bash
# 1. Remove existing torch (and CUDA siblings, if present)
pip uninstall -y torch torchvision torchaudio

# 2. Install the CUDA build matching your setup (per the
#    https://pytorch.org/get-started/locally/ selector), e.g. CUDA 12.6:
pip install torch --index-url https://download.pytorch.org/whl/cu126
```

## Configuration

Create a `.env` file next to `ThatsCap.py`:

```ini
# Directories
MONITOR_DIR=C:\Medal\Clips\Garrys Mod
OUTPUT_DIR=C:\Medal\Clips\Garrys Mod
VIDEO_EXTS=.mp4,.avi,.mov
POLL_INTERVAL=60
SETTLE_SECONDS=5

# Transcription backend: local (Hugging Face) or google
RECOGNIZER=local

# Local model: any HF ASR model id (openai/whisper-small, openai/whisper-large-v3, ...)
HF_MODEL=openai/whisper-small
HF_DEVICE=auto          # auto, cpu, or cuda:0
HF_TOKEN=               # only needed for gated models

# Video encoding
VCODEC=libx264          # libx264, libx265, h264_nvenc, hevc_nvenc, av1_nvenc
V_PRESET=medium
V_QUALITY=20            # CRF for CPU codecs, CQ for NVENC

# Subtitle styling
SUB_FONT=Arial
SUB_FONTSIZE=28
SUB_COLOR=white
SUB_STROKE_COLOR=black
SUB_STROKE_WIDTH=1
SUB_MARGIN=60
```


| Variable                 | Default                | Description                                                               |
| ------------------------ | ---------------------- | ------------------------------------------------------------------------- |
| `MONITOR_DIR`            | *(required)*           | Folder watched for new clips (scanned recursively)                        |
| `OUTPUT_DIR`             | `MONITOR_DIR`          | Where captioned videos and `.srt` files are written (subfolders mirrored) |
| `VIDEO_EXTS`             | `.mp4,.avi,.mov`       | File extensions to process                                                |
| `POLL_INTERVAL`          | `60`                   | Seconds between scans                                                     |
| `SETTLE_SECONDS`         | `5`                    | Skip files modified more recently than this (probably still recording)    |
| `RECOGNIZER`             | `local`                | `local` (Hugging Face) or `google` (Web Speech API)                       |
| `HF_MODEL`               | `openai/whisper-small` | Any Hugging Face ASR model id — bigger = more accurate, slower            |
| `HF_DEVICE`              | `auto`                 | `auto`, `cpu`, or `cuda:0`                                                |
| `HF_TOKEN`               | *(empty)*              | Hugging Face token, only for gated models                                 |
| `VCODEC`                 | `libx264`              | `libx264`, `libx265`, `h264_nvenc`, `hevc_nvenc`, `av1_nvenc`             |
| `V_PRESET` / `V_QUALITY` | per codec              | Encoder preset and quality — defaults are auto-set per codec if unset     |
| `V_QMODE`                | `crf`                  | Only for custom codecs: `crf`, `cq`, or `qp`                              |
| `SUB_*`                  | see above              | Font, size, colours, outline, and bottom margin of burned subtitles       |


## Usage

```bash
python ThatsCap.py
```

The script loops forever: scan the folder → caption any uncaptioned clips → sleep `POLL_INTERVAL` seconds. Stop with `Ctrl+C`.

For each processed clip it writes, in `OUTPUT_DIR` (mirroring subfolders):

- `<name>_captioned.mp4` — the video with subtitles burned in (original audio re-encoded to AAC 192k)
- `<name>.srt` — the standalone subtitle file

A clip is considered done once its `_captioned` file exists, so restarting never re-captions old clips, and clips are written atomically so you never see half-finished output. Clips with no audio or no speech are recorded in `.captioner_processed` and skipped. Files that fail are retried on the next restart. Delete the `_captioned` output (and `.captioner_processed` if needed) to reprocess a clip.

## Recommended models


| Model                          | Size       | Notes                                 |
| ------------------------------ | ---------- | ------------------------------------- |
| `openai/whisper-tiny` / `base` | \~40–75 MB | Good for loud, clear game comms       |
| `openai/whisper-small`         | \~250 MB   | Best speed/accuracy balance (default) |
| `openai/whisper-medium`        | \~750 MB   | Noticeably better accuracy            |
| `openai/whisper-large-v3`      | \~1.5 GB   | Best accuracy — use `cuda:0`          |


## Troubleshooting

- **`MONITOR_DIR is not set` / `does not exist`** — check the path in `.env` (quotes not needed).
- **`ffmpeg/ffprobe was not found on PATH`** — install FFmpeg and add it to your `PATH`.
- **`subtitles` filter errors** — the script copies the `.srt` to a temp working dir before burning, so paths with spaces are fine; make sure your ffmpeg build includes libass.
- **Captions out of sync** — try a larger model (`HF_MODEL`).
- **`google` backend returns nothing** — it requires internet, only handles short clips, and has no timestamps (one caption for the whole clip), which is why `local` is the default.
- **GPU encoding fails** — `*_nvenc` codecs require an NVIDIA GPU with recent drivers.
- **Reset processed list** — delete `.captioner_processed` in the output folder.

## License

MIT
