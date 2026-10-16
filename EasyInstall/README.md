# ThatsCap for everyone (no tech skills needed)

You do **not** need Python, FFmpeg, Git, or anything else installed.
All you need is a Windows 10/11 PC and an internet connection.

## First time (about 5–15 minutes)

1. **Download the app**
   - Go to the ThatsCap GitHub page and click the green **Code** button, then **Download ZIP**.
   - Right-click the downloaded ZIP and choose **Extract All...**, then open the extracted folder.

2. **Run the setup**
   - Double-click **setup_windows.bat**.
   - If Windows asks "Windows protected your PC", click **More info** then **Run anyway**.
   - Wait while it installs what it needs (this downloads ~1–2 GB the first time — grab a cup of tea).
   - When finished, your browser opens the ThatsCap page automatically.

3. **Set it up in the browser**
   - Click **Browse...** and click through to the folder your clips appear in (for example `C:\Medal\Clips`).
   - Pick a caption quality (Balanced is a good default).
   - Tick the NVIDIA box if you have an NVIDIA graphics card.
   - Style your subtitles if you like, then click **Start captions**.

4. **That's it!** 🎉
   New clips in that folder are captioned automatically. Captioned copies appear next to the originals, named like `myclip_captioned.mp4`. Your original clips are never modified.

## Every time after that

Just double-click **Start ThatsCap.bat**. The browser page opens again and captions continue where they left off.

## Handy to know

- The caption tool only runs while the black command window is open. Minimise it — don't close it — while you want captions to keep working.
- If a clip has no talking in it, it is skipped (that's normal).
- Captions come from an AI, so they are not always perfect. Choosing "Accurate" in the web page gives better results.
- To re-caption a clip, delete its `_captioned` file and restart.
- To see finished clips, use **Open output folder** on the web page.

## Something went wrong?

- **Setup said it could not find "winget"** — update Windows (Settings → Windows Update), then run setup again.
- **Setup says "Python installed but not found"** — restart your PC and run setup_windows.bat again.
- **"Windows protected your PC"** — the file is a plain script from this repo; click More info → Run anyway.
- **Captions look wrong or out of sync** — pick a higher quality in the web page, or untick the NVIDIA box if things fail.
- Anything else: check the log panel on the web page, and the `captioner.log` file in this folder.