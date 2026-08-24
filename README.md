# FEAR — File Encryption And Reader (v3)

A desktop app with three tabs: **Encrypt**, **Read** (a growing library of
decrypted previews with a mini media player), and **Decrypt / Remove
encryption**.

v3 is a **visual overhaul only** — a sci-fi HUD interface (angular
cut-corner panels, glowing cyan/magenta/amber accents, Orbitron + Rajdhani
type) replaces the default Qt look. Every encryption, decryption, library,
and playback behavior is unchanged from v2; see `CHANGES_v3.md` for exactly
what did and didn't change.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python test_crypto.py           # optional: confirm crypto works on your machine
python app.py                   # launch the app
```

Requires Python 3.9+. Tested on Python 3.12. First launch registers the
bundled Orbitron/Rajdhani fonts from `assets/fonts/` — no internet access
or system font install needed.

## The Encrypt / Decrypt tabs

Unchanged from v1/v2 — drop a file, set a password, get `yourfile.ext.fear`
back; or drop a `.fear` file, enter the password, and save the original
back out through a normal "Save As" dialog.

## The Read tab: library, alpha, and Now Playing

Every file you successfully unlock is **added** to a library (not replaced)
so you can drop several files across a session and browse all of them:

- **The library list** — each unlocked file appears as a HUD card: a
  thumbnail, a kind tag like `VIDEO 1` / `AUDIO 1` / `VIDEO 2`
  (auto-numbered per type, color-coded by kind), and the original filename.
  Images get a real thumbnail immediately; video gets a real frame grabbed
  from the file itself, with a placeholder icon shown until that resolves
  or if it fails; audio and archives get a themed icon.
- **Click a video/audio row** → it starts playing in the mini bar docked to
  the bottom of the window. Click a different row while something's
  already playing and it switches to that one instead.
- **The mini bar** shows a small *live* video preview (not just a static
  thumbnail) for video, the title, a seek bar, play/pause, and a loop
  toggle. Click anywhere on the bar itself (not the buttons) to expand.
- **Expanded ("Now Playing") view** shows the video large with the same
  transport controls, plus a "Back to library" button — the unlock-file
  form above collapses out of the way so this view gets full room. Double-
  click the video to jump to real OS fullscreen, with the same controls
  still visible; double-click again, click "Exit fullscreen," or press
  **Esc** to come back.
- **Images** skip the mini player entirely — clicking one opens a
  fullscreen viewer with **←/→** arrow keys (or the on-screen ‹ › buttons)
  to move between every image currently in the library. Esc closes it.
- **Archives** (`.zip`/`.rar`) open a dialog listing their contents, with
  an "Extract selected file..." button.
- **Anything else** offers to decrypt and open with your system's default
  app for that file type.
- **"Clear library"** securely wipes every decrypted temp file from the
  current session and empties the list, without needing to close the app.

### A note on how thumbnails and playback actually work

- Video/audio/archives get decrypted to a real temporary file on disk,
  because Qt's media player and Python's zip/rar readers need an actual
  file path — the library's contents don't live only in memory. This means
  multiple decrypted files can sit on disk simultaneously for as long as
  they're in your library. Everything gets securely wiped when you hit
  "Clear library" or close the app, but while the app is open with a full
  library, more plaintext is present on disk at once than a single-file
  workflow would have. If that tradeoff doesn't work for you, clear the
  library right after you're done browsing, or avoid loading many
  sensitive files into the same session.
- Video thumbnails are extracted by briefly loading the file in an
  invisible player and grabbing a real decoded frame. This depends on your
  system having a working video codec backend (FFmpeg-based on Linux;
  platform multimedia frameworks on Windows/Mac), so on some machines or
  unusual codecs it may time out and fall back to the plain video icon
  instead — that's an expected, harmless fallback, not a crash.
- Images are kept decrypted in memory only (no temp file needed for those).

### Other things worth knowing

- The mini bar lives inside the Read tab, not the whole app — if you
  switch to the Encrypt or Decrypt tab while something's playing, playback
  keeps going (audio especially), but the mini bar itself is out of view
  until you switch back to Read.
- Only one thing plays at a time, by design (clicking a new item stops the
  old one) — there's no queue/playlist auto-advance.

## The crypto, briefly

- **AES-256-GCM** for the actual encryption — authenticated, so a modified
  ciphertext is detected on decrypt, not just silently garbled.
- **Argon2id** to turn your password into the AES key, with strong default
  cost settings (256 MB memory, 4 passes) — this is what makes brute-forcing
  expensive. Full format details are documented at the top of
  `crypto_core.py`.
- A fresh random salt + nonce per file, and the original filename is stored
  *inside* the encrypted payload, not in a plaintext header.

`crypto_core.py` has zero GUI dependencies, so you can import and test it
on its own — that's what `test_crypto.py` does (roundtrip, wrong password,
tampering detection, and garbage-file rejection are all covered). It's
also untouched in v3, byte-for-byte identical to v2.

## Please read this part

- **There is no password recovery, on purpose.** Forget it and the file is
  permanently unrecoverable. Use a password manager or write it down
  somewhere safe.
- **The password is the real bottleneck**, not the algorithm. Aim for a
  long passphrase — the built-in strength meter is a rough heuristic, not
  a guarantee.
- **This hides file contents, not file existence.** A `.fear` file's
  presence, approximate size, and timestamps are still visible to anyone
  with drive access.
- **Deleted temp files use best-effort overwrite-then-delete**, which
  isn't a forensic guarantee on SSDs (wear leveling). Run FEAR on a
  fully disk-encrypted machine if that gap matters to you.
- **The Read tab's library keeps more plaintext on disk at once** than a
  single-file workflow would — see the note above. Use "Clear library"
  when you're done.

## Known limitations / ideas for v4

- Encryption/decryption still runs on the main thread — large files can
  briefly pause the UI. Worth moving to a `QThread` eventually.
- RAR preview needs the `rarfile` package *and* the `unrar` binary
  installed separately — ZIP needs nothing extra.
- No playlist/queue auto-advance; no batch/folder encryption.
- No persistent app-wide mini player across tabs.
- For genuine "hide that this file exists" deniability (VeraCrypt-style
  hidden volumes), you'd want padding to fixed-size buckets and/or a
  container-within-a-container design — bigger than a v4 tweak.
- Want a real distributable app instead of "run with Python"? `pyinstaller
  --onefile --windowed app.py` packages this into a single executable
  (make sure to add `--add-data "assets:assets"` so the bundled fonts ship
  with it).

## Project files

| File | Purpose |
|---|---|
| `crypto_core.py` | All encryption/decryption logic. No GUI imports. Unchanged from v2. |
| `utils.py` | Password strength heuristic + secure temp-file deletion. Unchanged from v2. |
| `theme.py` | **New in v3.** Color palette, bundled fonts, global stylesheet, and the reusable HUD widgets (panels, buttons, brackets, live dot, progress bar) every other file builds on. |
| `icons.py` | Self-drawn placeholder thumbnails (no external image assets), recolored per-kind to match the theme. |
| `drop_area.py` | Shared drag-and-drop widget used by all three tabs, now an angular HUD drop zone. |
| `library.py` | `LibraryItem` data model + the clickable HUD card list. |
| `player_bar.py` | Mini player bar ("alpha"), Now Playing view, fullscreen window. |
| `image_viewer.py` | Fullscreen image lightbox with prev/next navigation. |
| `encrypt_tab.py` | The Encrypt tab. |
| `read_tab.py` | The Read tab — wires library + player + lightbox + archives together. |
| `decrypt_tab.py` | The Decrypt tab. |
| `app.py` | Entry point — brand header, nav bar, and the main window that assembles the three tabs. |
| `test_crypto.py` | Standalone tests for `crypto_core.py`. Unchanged from v2. |
| `requirements.txt` | Dependencies (unchanged from v2 — the UI overhaul added no new runtime dependencies). |
| `assets/fonts/` | Bundled Orbitron + Rajdhani font files (OFL-licensed) so the look doesn't depend on the fonts being installed system-wide. |
