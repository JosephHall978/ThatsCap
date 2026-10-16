"""
ThatsCap - friendly web frontend.

Run:      python app.py  (or double-click "Start ThatsCap.bat")
Opens:    http://127.0.0.1:8399
"""
import os
import shutil
import string
import subprocess
import sys
import threading
import webbrowser
from collections import deque
from pathlib import Path

from flask import Flask, jsonify, request

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
PORT = 8399

app = Flask(__name__)

_log = deque(maxlen=2000)
_proc = None
_proc_lock = threading.Lock()

MODELS = {
    "fast": ("openai/whisper-small", "Fastest"),
    "balanced": ("openai/whisper-medium", "Recommended"),
    "accurate": ("openai/whisper-large-v3", "Most accurate (slower)"),
}
FONTS = ["Arial", "Verdana", "Tahoma", "Trebuchet MS", "Comic Sans MS", "Impact", "Georgia", "Times New Roman"]
COLORS = ["white", "yellow", "cyan", "orange", "red", "green", "gray", "black"]


def read_env() -> dict:
    cfg = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.strip()
    return cfg


def write_env(cfg: dict) -> None:
    gpu = bool(cfg.get("gpu"))
    model = MODELS.get(cfg.get("model", "balanced"), MODELS["balanced"])[0]
    lines = [
        "# ThatsCap settings (written by the web app)",
        "MONITOR_DIR=" + cfg["monitor_dir"],
        "OUTPUT_DIR=" + (cfg.get("output_dir") or cfg["monitor_dir"]),
        "VIDEO_EXTS=.mp4,.avi,.mov,.mkv,.webm,.wmv,.m4v",
        "POLL_INTERVAL=60",
        "SETTLE_SECONDS=5",
        "RECOGNIZER=local",
        "HF_MODEL=" + model,
        "HF_DEVICE=" + ("cuda:0" if gpu else "cpu"),
        "VCODEC=" + ("h264_nvenc" if gpu else "libx264"),
        "SUB_FONT=" + str(cfg.get("sub_font", "Arial")),
        "SUB_FONTSIZE=" + str(cfg.get("sub_fontsize", 28)),
        "SUB_COLOR=" + str(cfg.get("sub_color", "white")),
        "SUB_STROKE_COLOR=" + str(cfg.get("sub_stroke_color", "black")),
        "SUB_STROKE_WIDTH=" + str(cfg.get("sub_stroke_width", 1)),
        "SUB_MARGIN=" + str(cfg.get("sub_margin", 60)),
    ]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def _reader(stream) -> None:
    for raw in iter(stream.readline, ""):
        _log.append(raw.rstrip())


def _settings() -> dict:
    cfg = read_env()
    model = cfg.get("HF_MODEL", "")
    key = "balanced"
    for k, (mid, _) in MODELS.items():
        if mid == model:
            key = k
    return {
        "monitor_dir": cfg.get("MONITOR_DIR", ""),
        "output_dir": cfg.get("OUTPUT_DIR", ""),
        "model": key,
        "gpu": cfg.get("HF_DEVICE", "") == "cuda:0",
        "sub_font": cfg.get("SUB_FONT", "Arial"),
        "sub_fontsize": cfg.get("SUB_FONTSIZE", "28"),
        "sub_color": cfg.get("SUB_COLOR", "white"),
        "sub_stroke_color": cfg.get("SUB_STROKE_COLOR", "black"),
        "sub_stroke_width": cfg.get("SUB_STROKE_WIDTH", "1"),
        "sub_margin": cfg.get("SUB_MARGIN", "60"),
    }


@app.get("/api/status")
def api_status():
    return jsonify(
        running=is_running(),
        ffmpeg_ok=shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None,
        settings=_settings(),
        log=list(_log)[-200:],
    )


@app.post("/api/start")
def api_start():
    global _proc
    cfg = request.get_json(force=True)
    if not cfg.get("monitor_dir"):
        return jsonify(ok=False, error="Pick a clips folder first")
    if not os.path.isdir(cfg["monitor_dir"]):
        return jsonify(ok=False, error="That folder does not exist")
    write_env(cfg)
    with _proc_lock:
        if is_running():
            return jsonify(ok=False, error="Already running")
        _log.clear()
        _proc = subprocess.Popen(
            [sys.executable, str(BASE_DIR / "ThatsCap.py")],
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    threading.Thread(target=_reader, args=(_proc.stdout,), daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/stop")
def api_stop():
    global _proc
    if not is_running():
        return jsonify(ok=False, error="Not running")
    _proc.terminate()
    try:
        _proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _proc.kill()
    _log.append("--- stopped ---")
    return jsonify(ok=True)


@app.get("/api/browse")
def api_browse():
    p = (request.args.get("path") or "").strip()
    if not p:
        drives = []
        for letter in string.ascii_uppercase:
            d = letter + ":\\"
            if os.path.isdir(d):
                drives.append(d)
        return jsonify(path="", parent="", dirs=drives)
    p = os.path.abspath(p)
    if not os.path.isdir(p):
        return jsonify(error="Not a folder"), 400
    dirs = []
    try:
        for e in os.scandir(p):
            if e.is_dir() and not e.name.startswith((".", "$")):
                dirs.append(e.name)
    except PermissionError:
        pass
    parent = os.path.dirname(p)
    return jsonify(path=p, parent=parent if parent != p else "", dirs=sorted(dirs))


@app.post("/api/open")
def api_open():
    d = (request.get_json(force=True) or {}).get("dir", "")
    if d and os.path.isdir(d):
        try:
            os.startfile(d)
        except AttributeError:
            subprocess.Popen(["xdg-open", d])
    return jsonify(ok=True)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ThatsCap</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --bg:#0f1117; --card:#181b25; --line:#2a2f3d; --txt:#e8eaf0; --dim:#9aa1b2; --acc:#7c5cff; --ok:#2ecc71; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--txt); }
  .wrap { max-width:760px; margin:0 auto; padding:24px 16px 60px; }
  h1 { font-size:26px; margin:8px 0 2px; }
  .sub { color:var(--dim); margin:0 0 22px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px; margin-bottom:16px; }
  .card h2 { font-size:15px; text-transform:uppercase; letter-spacing:.06em; color:var(--dim); margin:0 0 12px; }
  label { display:block; font-size:14px; margin:10px 0 4px; }
  input[type=text], select { width:100%; padding:9px 11px; border-radius:8px; border:1px solid var(--line); background:#11131b; color:var(--txt); font-size:14px; }
  .row { display:flex; gap:12px; } .row > div { flex:1; }
  .btn { display:inline-block; border:0; border-radius:10px; padding:11px 18px; font-size:15px; font-weight:600; cursor:pointer; color:#fff; background:var(--acc); }
  .btn.ghost { background:#232838; }
  .btn.stop { background:#c0392b; }
  .btn:disabled { opacity:.5; cursor:default; }
  .btn.small { padding:6px 12px; font-size:13px; }
  .badge { display:inline-block; padding:3px 10px; border-radius:999px; font-size:13px; font-weight:600; }
  .badge.on { background:rgba(46,204,113,.15); color:var(--ok); }
  .badge.off { background:rgba(255,255,255,.08); color:var(--dim); }
  #log { background:#0b0d13; border:1px solid var(--line); border-radius:8px; padding:10px; height:220px; overflow-y:auto; font:12px/1.5 Consolas,monospace; white-space:pre-wrap; color:#b9c0d0; }
  .browsebox { display:none; margin-top:8px; background:#11131b; border:1px solid var(--line); border-radius:8px; max-height:230px; overflow-y:auto; }
  .browsebox div { padding:7px 12px; cursor:pointer; font-size:14px; }
  .browsebox div:hover { background:#232838; }
  .browsebox .up { color:var(--acc); font-weight:600; }
  .warn { background:rgba(230,126,34,.12); border:1px solid rgba(230,126,34,.4); color:#f0a35e; padding:10px 12px; border-radius:8px; margin-bottom:14px; font-size:14px; display:none; }
  .hint { color:var(--dim); font-size:12.5px; margin-top:4px; }
  .steps { display:flex; gap:10px; margin:18px 0; }
  .steps button { flex:1; }
</style>
</head>
<body>
<div class="wrap">
  <h1>&#127916; ThatsCap</h1>
  <p class="sub">Automatically add captions to your gameplay clips. Pick a folder, press Start, done.</p>
  <div class="warn" id="ffwarn">&#9888; FFmpeg was not found. Re-run <b>setup_windows.bat</b> (or restart your PC) to fix this.</div>

  <div class="card">
    <h2>1 &middot; Your clips folder</h2>
    <label>Folder where your clips appear (e.g. your Medal / OBS clips folder)</label>
    <div class="row">
      <div><input type="text" id="monitor_dir" placeholder="C:\Medal\Clips"></div>
      <div style="flex:0 0 auto"><button class="btn ghost small" onclick="openBrowse('monitor_dir')">Browse&#8230;</button></div>
    </div>
    <div class="browsebox" id="browsebox_monitor_dir"></div>
    <label>Captioned clips are saved to <span style="color:var(--dim)">(leave as the same folder)</span></label>
    <div class="row">
      <div><input type="text" id="output_dir" placeholder="Same as clips folder"></div>
      <div style="flex:0 0 auto"><button class="btn ghost small" onclick="openBrowse('output_dir')">Browse&#8230;</button></div>
    </div>
    <div class="browsebox" id="browsebox_output_dir"></div>
  </div>

  <div class="card">
    <h2>2 &middot; Caption quality</h2>
    <label for="model">Accuracy vs speed</label>
    <select id="model">
      <option value="fast">Fast &mdash; quick, fine for clear comms</option>
      <option value="balanced" selected>Balanced &mdash; recommended</option>
      <option value="accurate">Accurate &mdash; best captions, slower</option>
    </select>
    <label style="display:flex; align-items:center; gap:8px; margin-top:14px;">
      <input type="checkbox" id="gpu" style="width:16px;height:16px">
      I have an <b>NVIDIA</b> graphics card &mdash; use it (much faster)
    </label>
  </div>

  <div class="card">
    <h2>3 &middot; Subtitle look</h2>
    <div class="row">
      <div>
        <label>Font</label>
        <select id="sub_font"></select>
      </div>
      <div>
        <label>Size</label>
        <select id="sub_fontsize"></select>
      </div>
    </div>
    <div class="row">
      <div><label>Text colour</label><select id="sub_color"></select></div>
      <div><label>Outline colour</label><select id="sub_stroke_color"></select></div>
      <div><label>Outline width</label><select id="sub_stroke_width"></select></div>
    </div>
    <div style="text-align:center; margin-top:14px; background:#000; border-radius:8px; padding:18px 8px;">
      <span id="preview" style="font-size:22px;">This is how your captions will look</span>
    </div>
  </div>

  <div class="card">
    <h2>4 &middot; Run</h2>
    <span class="badge off" id="badge">&#9679; Not running</span>
    <div class="steps">
      <button class="btn" id="startbtn" onclick="startCap()">&#9654; Start captions</button>
      <button class="btn stop" id="stopbtn" onclick="stopCap()" disabled>&#9632; Stop</button>
    </div>
    <div id="log">Not started yet.</div>
    <p class="hint">Keep this window running. New clips get captioned automatically &mdash; look for files ending in <b>_captioned</b> next to your clips. <a href="#" style="color:var(--acc)" onclick="openOutput();return false">Open output folder</a></p>
  </div>
</div>

<script>
var FONTS = __FONTS__;
var COLORS = __COLORS__;
var browseTarget = 'monitor_dir';

function fill(id, arr, val) {
  var el = document.getElementById(id);
  el.innerHTML = '';
  for (var i = 0; i < arr.length; i++) {
    var o = document.createElement('option');
    o.value = arr[i]; o.textContent = arr[i];
    if (String(arr[i]) === String(val)) o.selected = true;
    el.appendChild(o);
  }
}

function refreshPreview() {
  var p = document.getElementById('preview');
  p.style.fontFamily = document.getElementById('sub_font').value;
  p.style.fontSize = document.getElementById('sub_fontsize').value + 'px';
  p.style.color = document.getElementById('sub_color').value;
  p.style.textShadow = '0 0 ' + (document.getElementById('sub_stroke_width').value * 2) + 'px ' + document.getElementById('sub_stroke_color').value + ', 0 0 ' + (document.getElementById('sub_stroke_width').value * 2) + 'px ' + document.getElementById('sub_stroke_color').value;
}

function openBrowse(target) {
  browseTarget = target;
  var box = document.getElementById('browsebox_' + target);
  if (box.style.display === 'block') { box.style.display = 'none'; return; }
  box.style.display = 'block';
  loadBrowse(document.getElementById(target).value || '');
}

function loadBrowse(path) {
  fetch('/api/browse?path=' + encodeURIComponent(path)).then(function (r) { return r.json(); }).then(function (d) {
    var box = document.getElementById('browsebox_' + browseTarget);
    box.innerHTML = '';
    var cur = document.createElement('div');
    cur.className = 'up';
    cur.textContent = (d.path || 'This PC') + '  ' + (d.path ? '(click here to use this folder)' : '');
    cur.onclick = function () {
      if (d.path) { document.getElementById(browseTarget).value = d.path; box.style.display = 'none'; }
    };
    box.appendChild(cur);
    if (d.parent) {
      var up = document.createElement('div');
      up.textContent = '\u2191 ..';
      up.onclick = function () { loadBrowse(d.parent); };
      box.appendChild(up);
    }
    d.dirs.forEach(function (name) {
      var row = document.createElement('div');
      row.textContent = '\U0001F4C1 ' + name;
      row.onclick = function () { loadBrowse((d.path ? d.path + '\\' : '') + name); };
      box.appendChild(row);
    });
    if (!d.dirs.length && d.path) {
      var none = document.createElement('div');
      none.textContent = '(no subfolders)';
      none.style.color = '#9aa1b2';
      box.appendChild(none);
    }
  });
}

function collect() {
  return {
    monitor_dir: document.getElementById('monitor_dir').value,
    output_dir: document.getElementById('output_dir').value || document.getElementById('monitor_dir').value,
    model: document.getElementById('model').value,
    gpu: document.getElementById('gpu').checked,
    sub_font: document.getElementById('sub_font').value,
    sub_fontsize: document.getElementById('sub_fontsize').value,
    sub_color: document.getElementById('sub_color').value,
    sub_stroke_color: document.getElementById('sub_stroke_color').value,
    sub_stroke_width: document.getElementById('sub_stroke_width').value,
    sub_margin: 60
  };
}

function startCap() {
  fetch('/api/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collect()) })
    .then(function (r) { return r.json(); }).then(function (d) { if (!d.ok) alert(d.error || 'Could not start'); poll(); });
}
function stopCap() {
  fetch('/api/stop', { method: 'POST' }).then(function () { poll(); });
}
function openOutput() {
  var d = document.getElementById('output_dir').value || document.getElementById('monitor_dir').value;
  if (d) fetch('/api/open', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dir: d }) });
}

var wasInit = false;
function poll() {
  fetch('/api/status').then(function (r) { return r.json(); }).then(function (s) {
    document.getElementById('ffwarn').style.display = s.ffmpeg_ok ? 'none' : 'block';
    var running = s.running;
    var badge = document.getElementById('badge');
    badge.className = 'badge ' + (running ? 'on' : 'off');
    badge.textContent = running ? '\u25CF Running' : '\u25CF Not running';
    document.getElementById('startbtn').disabled = running;
    document.getElementById('stopbtn').disabled = !running;
    if (s.log && s.log.length) {
      var el = document.getElementById('log');
      var atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
      el.textContent = s.log.join('\n');
      if (atBottom) el.scrollTop = el.scrollHeight;
    }
    if (!wasInit) {
      document.getElementById('monitor_dir').value = s.settings.monitor_dir || '';
      document.getElementById('output_dir').value = (s.settings.output_dir === s.settings.monitor_dir) ? '' : (s.settings.output_dir || '');
      document.getElementById('model').value = s.settings.model || 'balanced';
      document.getElementById('gpu').checked = !!s.settings.gpu;
      fill('sub_font', FONTS, s.settings.sub_font || 'Arial');
      fill('sub_color', COLORS, s.settings.sub_color || 'white');
      fill('sub_stroke_color', COLORS, s.settings.sub_stroke_color || 'black');
      var sizes = []; for (var i = 16; i <= 48; i += 2) sizes.push(i);
      fill('sub_fontsize', sizes, s.settings.sub_fontsize || 28);
      var widths = [0, 1, 2, 3, 4];
      fill('sub_stroke_width', widths, s.settings.sub_stroke_width || 1);
      ['sub_font', 'sub_fontsize', 'sub_color', 'sub_stroke_color', 'sub_stroke_width'].forEach(function (id) {
        document.getElementById(id).addEventListener('change', refreshPreview);
      });
      refreshPreview();
      wasInit = true;
    }
  });
}
poll();
setInterval(poll, 2000);
</script>
</body>
</html>
"""


@app.get("/")
def index():
    import json as _json
    html = PAGE.replace("__FONTS__", _json.dumps(FONTS)).replace("__COLORS__", _json.dumps(COLORS))
    return html


if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:%d" % PORT)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False)