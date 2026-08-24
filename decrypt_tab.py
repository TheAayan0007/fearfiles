"""FEAR - Decrypt tab."""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QMessageBox, QFileDialog

import crypto_core
from drop_area import DropArea
from theme import C, HUDButton, StatusLabel, section_label, field_caption, CenteredColumn


class DecryptTab(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_path = None

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 22, 0, 20)
        layout.setSpacing(8)

        layout.addWidget(section_label("Encrypted File"))
        self.drop_area = DropArea("Drag & drop a .fear file to decrypt")
        self.drop_area.fileDropped.connect(self.on_file_selected)
        layout.addWidget(self.drop_area)

        layout.addWidget(section_label("Password"))
        layout.addWidget(field_caption("Password"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Enter the password used to encrypt this file")
        self.password_input.returnPressed.connect(self.do_decrypt)
        layout.addWidget(self.password_input)

        toggle_row = QHBoxLayout()
        toggle_row.addStretch()
        self.show_pw_btn = HUDButton("SHOW PASSWORD", variant="ghost", checkable=True, cut=6)
        self.show_pw_btn.setMinimumHeight(28)
        self.show_pw_btn.toggled.connect(self.toggle_visibility)
        toggle_row.addWidget(self.show_pw_btn)
        layout.addLayout(toggle_row)

        layout.addSpacing(6)
        self.decrypt_btn = HUDButton("DECRYPT & SAVE AS...", variant="primary", cut=12)
        self.decrypt_btn.setMinimumHeight(44)
        self.decrypt_btn.clicked.connect(self.do_decrypt)
        layout.addWidget(self.decrypt_btn)

        self.status_label = StatusLabel()
        layout.addWidget(self.status_label)
        layout.addStretch()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 0, 28, 0)
        outer.addWidget(CenteredColumn(inner, max_width=760))

    def on_file_selected(self, path):
        self.selected_path = path
        self.drop_area.set_filename(path)
        self.status_label.clear_status()

    def toggle_visibility(self, checked):
        self.password_input.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def do_decrypt(self):
        if not self.selected_path:
            QMessageBox.warning(self, "No file", "Please select a .fear file first.")
            return
        pw = self.password_input.text()
        try:
            with open(self.selected_path, "rb") as f:
                data = f.read()
            metadata, original_bytes = crypto_core.decrypt_bytes(data, pw)
        except crypto_core.DecryptionError as e:
            QMessageBox.critical(self, "Can't decrypt", str(e))
            self.status_label.set_status("Decryption failed.", "error")
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self.status_label.set_status("Decryption failed.", "error")
            return
        finally:
            self.password_input.clear()

        suggested_name = metadata.get("filename", "decrypted_file")
        save_path, _ = QFileDialog.getSaveFileName(self, "Save decrypted file as", suggested_name)
        if save_path:
            with open(save_path, "wb") as f:
                f.write(original_bytes)
            self.status_label.set_status(f"Saved to: {save_path}", "success")
            QMessageBox.information(self, "Success", f"Decrypted and saved:\n{save_path}")
