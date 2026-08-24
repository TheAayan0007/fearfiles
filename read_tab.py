"""
FEAR - Read tab. Drop/unlock files to add them to a growing library.
Video/audio play through a single shared QMediaPlayer via the alpha mini
bar -> Now Playing -> fullscreen chain (player_bar.py). Images open in a
fullscreen lightbox with prev/next across all images in the library
(image_viewer.py). Archives and other file types keep the list/extract and
decrypt-and-open-externally behavior from v1.
"""

import os
import zipfile
import tempfile

from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QPixmap, QImage, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QStackedWidget, QFileDialog, QDialog, QListWidget,
    QScrollArea, QFrame
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink

import crypto_core
from utils import secure_delete
from drop_area import DropArea
from library import LibraryItem, LibraryListView, THUMB_SIZE
from player_bar import AlphaBar, NowPlayingView, FullscreenVideoWindow
from theme import (
    C, HUDButton, StatusLabel, section_label, field_caption, display_font, body_font,
    CenteredColumn,
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"}
ARCHIVE_EXTS = {".zip", ".rar"}

THUMBNAIL_PROBE_TIMEOUT_MS = 3000


class ReadTab(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_path = None
        self.library = []
        self.cards_by_id = {}
        self.current_item = None
        self._decrypted_temp_files = []
        self._thumb_probes = []  # keeps probe QMediaPlayer/QVideoSink pairs alive

        # One shared player for everything alpha/Now-Playing/fullscreen touch.
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.errorOccurred.connect(self._on_player_error)

        self.fullscreen_window = None

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 22, 0, 14)
        layout.setSpacing(8)

        # --- "browse" page: unlock form + library, scrolled TOGETHER as one
        # unit. Nothing in here ever shrinks or gets compressed to make
        # room for a growing library -- everything stays at its natural
        # size, and a scrollbar appears once it's taller than the window.
        browse_content = QWidget()
        browse_content.setStyleSheet("background: transparent;")
        browse_layout = QVBoxLayout(browse_content)
        browse_layout.setContentsMargins(0, 0, 10, 4)
        browse_layout.setSpacing(8)

        browse_layout.addWidget(section_label("Unlock File"))
        self.drop_area = DropArea("Drag & drop a .fear file to add it to your library")
        self.drop_area.fileDropped.connect(self.on_file_selected)
        browse_layout.addWidget(self.drop_area)

        browse_layout.addWidget(field_caption("Password"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Enter the password used to encrypt this file")
        self.password_input.returnPressed.connect(self.do_unlock)
        browse_layout.addWidget(self.password_input)

        self.unlock_btn = HUDButton("UNLOCK & ADD TO LIBRARY", variant="primary", cut=12)
        self.unlock_btn.setMinimumHeight(42)
        self.unlock_btn.clicked.connect(self.do_unlock)
        browse_layout.addWidget(self.unlock_btn)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.status_label = StatusLabel()
        status_row.addWidget(self.status_label, 1)
        clear_btn = HUDButton("CLEAR LIBRARY", variant="danger", cut=6)
        clear_btn.setMinimumHeight(28)
        clear_btn.setToolTip("Securely wipes decrypted temp copies from this session")
        clear_btn.clicked.connect(self.clear_library)
        status_row.addWidget(clear_btn, 0, Qt.AlignRight)
        browse_layout.addLayout(status_row)

        browse_layout.addWidget(section_label("Library"))
        self.library_view = LibraryListView()
        self.library_view.itemClicked.connect(self.handle_item_clicked)
        browse_layout.addWidget(self.library_view)
        browse_layout.addStretch()

        scroll_area = QScrollArea()
        scroll_area.setWidget(browse_content)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll_area.viewport().setStyleSheet("background: transparent;")

        # --- browse (scrollable) <-> Now Playing (fixed, fills full height) ---
        self.main_stack = QStackedWidget()
        self.main_stack.addWidget(scroll_area)                # index 0

        self.now_playing = NowPlayingView()
        self.now_playing.minimizeRequested.connect(self.minimize_now_playing)
        self.now_playing.fullscreenRequested.connect(self.enter_fullscreen)
        self.now_playing.playPauseClicked.connect(self.toggle_play_pause)
        self.now_playing.seekRequested.connect(self.player.setPosition)
        self.now_playing.loopToggled.connect(self.set_looping)
        self.main_stack.addWidget(self.now_playing)            # index 1

        layout.addWidget(self.main_stack, 1)

        # --- "alpha": bottom-docked mini player, stays put regardless of
        # scroll position in the browse page above it ---
        self.alpha_bar = AlphaBar()
        self.alpha_bar.expandRequested.connect(self.expand_to_now_playing)
        self.alpha_bar.playPauseClicked.connect(self.toggle_play_pause)
        self.alpha_bar.seekRequested.connect(self.player.setPosition)
        self.alpha_bar.loopToggled.connect(self.set_looping)
        self.alpha_bar.hide()
        layout.addWidget(self.alpha_bar)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 0, 28, 0)
        outer.addWidget(CenteredColumn(inner, max_width=760), 1)

    # ---------- unlocking / adding to library ----------

    def on_file_selected(self, path):
        self.selected_path = path
        self.drop_area.set_filename(path)
        self.status_label.clear_status()

    def do_unlock(self):
        if not self.selected_path:
            QMessageBox.warning(self, "No file", "Please select a .fear file first.")
            return
        pw = self.password_input.text()
        try:
            with open(self.selected_path, "rb") as f:
                data = f.read()
            metadata, original_bytes = crypto_core.decrypt_bytes(data, pw)
        except crypto_core.DecryptionError as e:
            QMessageBox.critical(self, "Can't open file", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        finally:
            self.password_input.clear()

        self._add_to_library(metadata, original_bytes)

    def _add_to_library(self, metadata, original_bytes):
        filename = metadata.get("filename", "file")
        ext = os.path.splitext(filename)[1].lower()

        if ext in IMAGE_EXTS:
            item = LibraryItem("image", filename, image_bytes=original_bytes)
            image = QImage.fromData(original_bytes)
            item.thumbnail = QPixmap.fromImage(image).scaled(
                THUMB_SIZE, THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        elif ext in VIDEO_EXTS or ext in AUDIO_EXTS:
            temp_path = self._write_temp(original_bytes, ext)
            kind = "video" if ext in VIDEO_EXTS else "audio"
            item = LibraryItem(kind, filename, temp_path=temp_path)
        elif ext in ARCHIVE_EXTS:
            temp_path = self._write_temp(original_bytes, ext)
            item = LibraryItem("archive", filename, temp_path=temp_path, archive_ext=ext)
        else:
            item = LibraryItem("generic", filename, image_bytes=original_bytes)

        self.library.append(item)
        card = self.library_view.add_item(item)
        self.cards_by_id[item.id] = card

        if item.kind == "video":
            self._request_video_thumbnail(item)

        self.status_label.set_status(f"Added to library: {filename}", "success")

    def _write_temp(self, data_bytes, ext):
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        tmp.write(data_bytes)
        tmp.close()
        self._decrypted_temp_files.append(tmp.name)
        return tmp.name

    # ---------- routing a library click ----------

    def handle_item_clicked(self, item):
        if item.kind in ("video", "audio"):
            self.play_item(item)
        elif item.kind == "image":
            self.open_image_viewer(item)
        elif item.kind == "archive":
            self.open_archive_dialog(item)
        else:
            self.open_generic_item(item)

    # ---------- alpha / now playing / fullscreen ----------

    def play_item(self, item):
        self.current_item = item
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(item.temp_path))

        if item.kind == "video":
            target = self.now_playing.video_widget if self.main_stack.currentIndex() == 1 \
                else self.alpha_bar.show_live_video()
            self.player.setVideoOutput(target)
        else:
            self.player.setVideoOutput(None)

        self.alpha_bar.set_now_playing(item)
        self.now_playing.set_now_playing(item)
        self.alpha_bar.show()
        self.player.play()

    def toggle_play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def expand_to_now_playing(self):
        if self.current_item is None:
            return
        self.main_stack.setCurrentIndex(1)
        if self.current_item.kind == "video":
            self.player.setVideoOutput(self.now_playing.video_widget)
        self.alpha_bar.hide()

    def minimize_now_playing(self):
        self.main_stack.setCurrentIndex(0)
        if self.current_item and self.current_item.kind == "video":
            target = self.alpha_bar.show_live_video()
            self.player.setVideoOutput(target)
        self.alpha_bar.show()

    def enter_fullscreen(self):
        if self.current_item is None or self.current_item.kind != "video":
            return
        if self.fullscreen_window is None:
            self.fullscreen_window = FullscreenVideoWindow()
            self.fullscreen_window.exitRequested.connect(self.exit_fullscreen)
            self.fullscreen_window.playPauseClicked.connect(self.toggle_play_pause)
            self.fullscreen_window.seekRequested.connect(self.player.setPosition)
            self.fullscreen_window.loopToggled.connect(self.set_looping)
        self.player.setVideoOutput(self.fullscreen_window.video_widget)
        self.fullscreen_window.showFullScreen()

    def exit_fullscreen(self):
        if self.fullscreen_window is not None:
            self.fullscreen_window.hide()
        if self.current_item and self.current_item.kind == "video":
            self.player.setVideoOutput(self.now_playing.video_widget)

    def set_looping(self, checked):
        self.player.setLoops(QMediaPlayer.Loops.Infinite if checked else QMediaPlayer.Loops.Once)
        for btn in self._loop_buttons():
            if btn.isChecked() != checked:
                btn.blockSignals(True)
                btn.setChecked(checked)
                btn.blockSignals(False)

    def _loop_buttons(self):
        buttons = [self.alpha_bar.loop_btn, self.now_playing.loop_btn]
        if self.fullscreen_window is not None:
            buttons.append(self.fullscreen_window.loop_btn)
        return buttons

    def _on_playback_state_changed(self, state):
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.alpha_bar.set_playing_state(is_playing)
        self.now_playing.set_playing_state(is_playing)
        if self.fullscreen_window is not None:
            self.fullscreen_window.set_playing_state(is_playing)

    def _on_position_changed(self, position):
        self._push_position(position, self.player.duration())

    def _on_duration_changed(self, duration):
        self._push_position(self.player.position(), duration)

    def _push_position(self, position, duration):
        self.alpha_bar.set_position(position, duration)
        self.now_playing.set_position(position, duration)
        if self.fullscreen_window is not None:
            self.fullscreen_window.set_position(position, duration)

    def _on_player_error(self, error, error_string):
        if error_string:
            self.status_label.set_status(f"Playback error: {error_string}", "error")

    # ---------- images ----------

    def open_image_viewer(self, item):
        # deferred import avoids a hard dependency for users who never open one
        from image_viewer import ImageLightbox
        images = [i for i in self.library if i.kind == "image"]
        index = images.index(item)
        viewer = ImageLightbox(images, index, parent=self)
        viewer.exec()

    # ---------- archives ----------

    def open_archive_dialog(self, item):
        dialog = QDialog(self)
        dialog.setWindowTitle(item.title)
        dialog.setStyleSheet(f"QDialog {{ background: {C.BG}; }}")
        dialog.resize(440, 360)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(section_label("Archive Contents"))
        listw = QListWidget()
        listw.setFont(body_font(14, "Medium", 0.2))
        layout.addWidget(listw)

        try:
            names = self._list_archive(item.temp_path, item.archive_ext)
        except ImportError:
            QMessageBox.information(
                self, "RAR support not installed",
                "Install the 'rarfile' Python package plus the 'unrar' tool "
                "on your system to preview RAR contents.",
            )
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not read archive: {e}")
            return
        for name in names:
            listw.addItem(name)

        def extract():
            sel = listw.currentItem()
            if not sel:
                return
            name = sel.text()
            try:
                content = self._read_archive_entry(item.temp_path, item.archive_ext, name)
            except Exception as e:
                QMessageBox.critical(dialog, "Error", str(e))
                return
            save_path, _ = QFileDialog.getSaveFileName(dialog, "Save extracted file", os.path.basename(name))
            if save_path:
                with open(save_path, "wb") as f:
                    f.write(content)

        extract_btn = HUDButton("EXTRACT SELECTED FILE...", variant="primary", cut=10)
        extract_btn.setMinimumHeight(42)
        extract_btn.clicked.connect(extract)
        layout.addWidget(extract_btn)
        dialog.exec()

    @staticmethod
    def _list_archive(path, ext):
        if ext == ".zip":
            with zipfile.ZipFile(path) as zf:
                return zf.namelist()
        elif ext == ".rar":
            import rarfile
            with rarfile.RarFile(path) as rf:
                return rf.namelist()
        return []

    @staticmethod
    def _read_archive_entry(path, ext, name):
        if ext == ".zip":
            with zipfile.ZipFile(path) as zf:
                return zf.read(name)
        elif ext == ".rar":
            import rarfile
            with rarfile.RarFile(path) as rf:
                return rf.read(name)
        raise ValueError("Unsupported archive type")

    # ---------- generic files ----------

    def open_generic_item(self, item):
        reply = QMessageBox.question(
            self, item.title,
            "No built-in preview for this file type. Decrypt and open with your default app?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        ext = os.path.splitext(item.title)[1]
        temp_path = self._write_temp(item.image_bytes, ext)
        QDesktopServices.openUrl(QUrl.fromLocalFile(temp_path))

    # ---------- video thumbnails (best-effort real frame grab) ----------

    def _request_video_thumbnail(self, item):
        probe_player = QMediaPlayer()
        sink = QVideoSink()
        probe_player.setVideoSink(sink)
        self._thumb_probes.append((probe_player, sink))  # keep alive; GC'd on tab close
        state = {"done": False}

        def on_frame(frame):
            if state["done"] or not frame.isValid():
                return
            image = frame.toImage()
            if image.isNull():
                return
            state["done"] = True
            pixmap = QPixmap.fromImage(image).scaled(
                THUMB_SIZE, THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            item.thumbnail = pixmap
            card = self.cards_by_id.get(item.id)
            if card is not None:
                card.set_thumbnail(pixmap)
            probe_player.stop()

        sink.videoFrameChanged.connect(on_frame)
        probe_player.setSource(QUrl.fromLocalFile(item.temp_path))
        probe_player.play()

        def give_up():
            if not state["done"]:
                state["done"] = True
                probe_player.stop()
                # placeholder icon (already showing) stays as the thumbnail

        QTimer.singleShot(THUMBNAIL_PROBE_TIMEOUT_MS, give_up)

    # ---------- cleanup ----------

    def clear_library(self):
        if not self.library:
            return
        reply = QMessageBox.question(
            self, "Clear library",
            "This securely deletes every decrypted temp copy from this session "
            "and empties the library. Continue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._reset_player()
        self._wipe_temp_files()
        self.library.clear()
        self.cards_by_id.clear()
        self.library_view.clear()
        self.status_label.set_status("Library cleared.", "info")

    def _reset_player(self):
        self.player.stop()
        self.player.setSource(QUrl())
        self.current_item = None
        self.alpha_bar.hide()
        self.main_stack.setCurrentIndex(0)
        if self.fullscreen_window is not None:
            self.fullscreen_window.hide()

    def _wipe_temp_files(self):
        for path in self._decrypted_temp_files:
            try:
                secure_delete(path)
            except Exception:
                pass
        self._decrypted_temp_files.clear()

    def cleanup_on_close(self):
        self._reset_player()
        self._wipe_temp_files()
