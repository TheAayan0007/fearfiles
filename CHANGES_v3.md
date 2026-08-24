# What changed in v3

This was a **UI-only pass**. The goal was to reskin FEAR with the sci-fi
HUD look from your reference apps (Aayan Body Tracker, Aayan Globe,
Kindred) — same cyan/magenta/amber palette, Orbitron + Rajdhani type,
angular cut-corner panels, glow, corner brackets, live-dot status
indicators — without changing what the app *does*.

## Untouched, byte-for-byte identical to v2

- `crypto_core.py` — encryption format, AES-256-GCM, Argon2id parameters,
  all of it.
- `utils.py` — password strength scoring, secure delete.
- `test_crypto.py`, `requirements.txt`.

## New file

- **`theme.py`** — the whole design system lives here: the color palette,
  font loading/lookup, the global Qt stylesheet, and reusable HUD widgets
  (`HUDPanel`, `HUDButton`, `HUDProgressBar`, `LiveDot`, `CornerBrackets`,
  `StatusLabel`, plus label helpers). Every other file imports from this
  one rather than hardcoding colors, so the whole look can be re-tuned in
  one place later if you want to adjust it.
- **`assets/fonts/`** — Orbitron (Regular/Medium/Bold/Black) and Rajdhani
  (Light/Regular/Medium/SemiBold/Bold), OFL-licensed, instantiated as
  static weights from Google's variable-font source and bundled so the
  app looks right without needing the fonts installed system-wide or an
  internet connection at runtime.

## Restyled, same behavior

- `icons.py` — placeholder thumbnails redrawn on the HUD cut-corner shape;
  each file kind (video/audio/archive/generic) now has a distinct accent
  color, reused by the library list's kind tags.
- `drop_area.py` — angular dashed-border drop zone with corner brackets,
  switches to a solid glowing border once a file is selected. Same
  `DropArea` class, same `fileDropped` signal, same `set_filename()`
  method — nothing that imports it needed to change.
- `library.py` — library rows are now HUD cards with a kind-colored accent
  bar. `THUMB_SIZE` went from 64 to 72px for a bit more visual weight.
  Same `LibraryItem`, `LibraryListView`, `add_item()`/`clear()` API.
- `encrypt_tab.py` / `decrypt_tab.py` — same fields, same validation, same
  crypto calls, same dialogs — just laid out with section captions, the
  new drop zone, HUD buttons, and (Encrypt only) a glowing strength meter
  instead of the default `QProgressBar`.
- `player_bar.py` — the mini bar, Now Playing view, and fullscreen window
  all got the HUD treatment (glow buttons, HUD-styled slider, live-dot
  "NOW PLAYING" tag). Same signals, same shared-player wiring.
- `image_viewer.py` — same lightbox behavior (arrow keys, Esc, prev/next
  across the library's images), restyled chrome.
- `app.py` — the default `QTabWidget` tab strip is replaced with a custom
  nav bar (three HUD toggle buttons driving a `QStackedWidget`) so the
  active tab gets a proper glowing underline instead of the stock Qt tab
  look, plus a brand header ("FEAR // V3.0" with a live status dot). Same
  `closeEvent` → `read_tab.cleanup_on_close()` wiring.

## One small, deliberate UX change

`read_tab.py`: previously, the "unlock a file" form (drop zone, password
field, unlock button) stayed visible above the library/player area even
while a video or audio file was expanded to the full Now Playing view —
true in v2 as well, not something v3 introduced. With the new, more
visually substantial styling this got noticeably more cramped, so Now
Playing lives on its own page of the tab's `QStackedWidget` and gets the
full tab height while it's showing, and the library page (below) is what
you see the rest of the time.

## Read tab: nothing shrinks, the page scrolls instead

The unlock form (drop zone, password field, unlock button, status row)
and the library list used to compete for space inside the same fixed-
height area, which meant a small window or a long library could compress
the drop zone and cause visible overlap. Fixed by restructuring so the
unlock form and the library list are **one scrollable page together**:

- Nothing in that page has a size that depends on how much else is on the
  page or how tall the window is -- the drop zone, password field, and
  buttons are always their full natural size.
- `LibraryListView` no longer scrolls on its own (it's a plain list now,
  not a `QScrollArea`); the whole page -- unlock form and library list
  together -- scrolls as one unit inside a `QScrollArea` at the tab level.
  Add more files and the page gets taller; a scrollbar appears once it's
  taller than the window, instead of anything getting compressed.
- Now Playing (opened by clicking a video/audio row) is a separate page
  of the same stack and isn't part of that scroll area -- it still fills
  the full tab height for a proper player view.
- The bottom mini player ("alpha bar") sits below the scroll area, not
  inside it, so it stays docked in place regardless of scroll position.
- Fixed a real bug surfaced while restructuring this: the library's
  "empty" placeholder could get silently detached from the list after a
  clear-then-refill-then-clear-again cycle, so on the second clear it
  wouldn't reappear. Covered by a regression check now (clear, refill,
  clear again, confirm the placeholder comes back).

## Layout robustness fixes found during testing

While testing at different window sizes, real layout bugs turned up and got
fixed (not just papered over):

1. `DropArea` had a hardcoded minimum height smaller than what its own
   contents actually needed, so under vertical pressure Qt would compress
   it below that and text could overlap the panel below it. Fixed by
   trimming its internal padding and letting its real minimum size drive
   layout, instead of fighting Qt with a guessed constant.
2. The main window's minimum size was smaller than the tallest tab
   actually needs once you add up the header + nav bar + tab content.
   Verified against the real `minimumSizeHint()` of all three tabs and
   set the window minimum accordingly, so nothing clips or overlaps at
   any size the window allows you to resize to.
3. **The whole app was only ever tested around ~860px wide.** At a real
   desktop size -- and especially maximized on a 1920x1080 display, which
   is the common case on Windows -- password fields and the drop zone
   stretched edge-to-edge into absurdly wide boxes, because nothing
   capped their width. Fixed with a new `CenteredColumn` helper in
   `theme.py` that caps each tab's content to a comfortable max-width and
   centers it, the way a web app would with `max-width` + `margin: auto`.
   (Getting this right took a couple of tries -- a widget with an
   Expanding size policy sitting between two `addStretch()` spacers in a
   `QHBoxLayout` does *not* reliably grow to fill the space, because
   stretch-factor-0 items and Expanding spacer items don't have a
   well-defined priority order in Qt's box layout. The working version
   computes left/right margins directly from the widget's current width
   on `resizeEvent`, which has no such ambiguity.)
4. **The default window size was a flat guess (860x780)**, which looks
   small and off-center on a real screen. `theme.screen_default_size()`
   now sizes the window as a fraction of the actual screen's available
   geometry (clamped to a sane min/max), so on a 1920x1080 display it
   opens around 1113x885 and gets centered on screen, instead of a fixed
   size stuck in a corner.
5. **No explicit high-DPI handling** -- added
   `QApplication.setHighDpiScaleFactorRoundingPolicy(PassThrough)` before
   the `QApplication` is constructed. Qt6 enables high-DPI scaling by
   default, but on Windows with *fractional* scaling (125%/150%, the
   common case on most 1920x1080 laptop panels) the default rounding
   policy can size fonts/controls using the wrong physical pixel scale.
   `PassThrough` uses the OS's exact scale factor instead of rounding it.

I don't have a physical Windows machine to test on, so all of the above is
verified by simulating the relevant window/screen sizes (including a real
1920x1080-derived default) rather than by seeing it run natively on
Windows. If something still looks off once you actually run it, that's
useful signal -- it likely means there's a Windows- or DPI-specific detail
that simulation doesn't catch, so flag exactly what you're seeing (a
screenshot helps a lot) and it can be targeted directly instead of guessed
at again.

## Verification

Every tab was rendered and visually checked at both the default window
size and the minimum allowed size. Beyond that, the actual encrypt →
decrypt round trip was run through the real `EncryptTab.do_encrypt()` /
`DecryptTab.do_decrypt()` methods (not reimplemented for the test) on a
real file, confirming byte-for-byte identical output, correct wrong-
password handling, and the Read tab's unlock-to-library path — so this
isn't just a visual reskin that happens to run, the underlying app was
exercised end-to-end after the change.
