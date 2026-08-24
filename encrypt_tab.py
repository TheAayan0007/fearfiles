"""FEAR - Encrypt tab."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QApplication
)
from PySide6.QtCore import Qt

import crypto_core
from utils import password_strength_score, strength_label
from drop_area import DropArea
from theme import (
    C, HUDButton, HUDProgressBar, StatusLabel, section_label, field_caption,
    display_font, body_font, CenteredColumn,
)

_STRENGTH_COLOR = {"Weak": C.ACCENT2, "Okay": C.ACCENT3, "Strong": C.ACCENT, "Very strong": C.SUCCESS}


class EncryptTab(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_path = None

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 22, 0, 20)
        layout.setSpacing(8)

        layout.addWidget(section_label("Source File"))
        self.drop_area = DropArea("Drag & drop the file you want to encrypt")
        self.drop_area.fileDropped.connect(self.on_file_selected)
        layout.addWidget(self.drop_area)

        layout.addWidget(section_label("Password"))

        layout.addWidget(field_caption("Password"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Enter a password")
        self.password_input.textChanged.connect(self.update_strength)
        layout.addWidget(self.password_input)

        strength_row = QHBoxLayout()
        strength_row.setSpacing(10)
        self.strength_bar = HUDProgressBar()
        strength_row.addWidget(self.strength_bar, 1)
        self.strength_text = QLabel("")
        self.strength_text.setFont(display_font(10, "Bold", 1.4))
        self.strength_text.setMinimumWidth(84)
        self.strength_text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        strength_row.addWidget(self.strength_text)
        layout.addLayout(strength_row)

        layout.addWidget(field_caption("Confirm password"))
        self.confirm_input = QLineEdit()
        self.confirm_input.setEchoMode(QLineEdit.Password)
        self.confirm_input.setPlaceholderText("Re-enter the password")
        self.confirm_input.returnPressed.connect(self.do_encrypt)
        layout.addWidget(self.confirm_input)

        toggle_row = QHBoxLayout()
        toggle_row.addStretch()
        self.show_pw_btn = HUDButton("SHOW PASSWORD", variant="ghost", checkable=True, cut=6)
        self.show_pw_btn.setMinimumHeight(28)
        self.show_pw_btn.toggled.connect(self.toggle_visibility)
        toggle_row.addWidget(self.show_pw_btn)
        layout.addLayout(toggle_row)

        layout.addSpacing(6)
        self.encrypt_btn = HUDButton("ENCRYPT FILE", variant="primary", cut=12)
        self.encrypt_btn.setMinimumHeight(44)
        self.encrypt_btn.clicked.connect(self.do_encrypt)
        layout.addWidget(self.encrypt_btn)

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
        mode = QLineEdit.Normal if checked else QLineEdit.Password
        self.password_input.setEchoMode(mode)
        self.confirm_input.setEchoMode(mode)

    def update_strength(self, text):
        score = password_strength_score(text)
        self.strength_bar.setValue(score)
        label = strength_label(score) if text else ""
        color = _STRENGTH_COLOR.get(label, C.BORDER)
        self.strength_bar.setColor(color if text else C.BORDER)
        self.strength_text.setText(label.upper())
        self.strength_text.setStyleSheet(f"color: {color};")

    def do_encrypt(self):
        if not self.selected_path:
            QMessageBox.warning(self, "No file", "Please select a file first.")
            return
        pw = self.password_input.text()
        confirm = self.confirm_input.text()
        if not pw:
            QMessageBox.warning(self, "No password", "Please enter a password.")
            return
        if pw != confirm:
            QMessageBox.warning(self, "Mismatch", "Passwords don't match.")
            return
        if password_strength_score(pw) < 30:
            reply = QMessageBox.question(
                self, "Weak password",
                "This password looks weak — the encryption is only as strong "
                "as your password. Use it anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        out_path = self.selected_path + ".fear"
        self.status_label.set_status("Encrypting... this can take a few seconds.", "info")
        QApplication.processEvents()
        try:
            crypto_core.encrypt_file(self.selected_path, out_path, pw)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Encryption failed:\n{e}")
            self.status_label.clear_status()
            return
        finally:
            self.password_input.clear()
            self.confirm_input.clear()

        self.status_label.set_status(f"Done. Saved as: {out_path}", "success")
        QMessageBox.information(self, "Success", f"File encrypted:\n{out_path}")
