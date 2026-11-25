# SPDX-License-Identifier: Apache-2.0
"""Startup acknowledgement; read the same notice distributed with the app."""
from pathlib import Path


def disclaimer_text(root: Path) -> str:
    """Fail closed if the distributed notice is absent or empty."""
    text = (root / 'DISCLAIMER.md').read_text(encoding='utf-8').strip()
    if not text:
        raise ValueError('DISCLAIMER.md is empty; restore the original distribution.')
    return text


def confirm_usage_terms(root: Path) -> bool:
    # Keep Qt imports local so documentation checks work without GUI dependencies.
    from PySide6.QtWidgets import (
        QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
    )

    dialog = QDialog()
    dialog.setWindowTitle('Command Relay — Disclaimer / Отказ от ответственности')
    dialog.resize(760, 600)
    layout = QVBoxLayout(dialog)
    heading = QLabel('Review the risks before continuing / Ознакомьтесь с рисками')
    heading.setWordWrap(True)
    layout.addWidget(heading)
    notice = QPlainTextEdit()
    notice.setPlainText(disclaimer_text(root))
    notice.setReadOnly(True)
    layout.addWidget(notice, 1)
    buttons = QHBoxLayout()
    buttons.addStretch()
    decline = QPushButton('Decline and exit / Отказаться и выйти')
    decline.setObjectName('terms_decline')
    decline.setDefault(True)
    decline.clicked.connect(dialog.reject)
    agree = QPushButton('I understand and agree / Понимаю и принимаю')
    agree.setObjectName('terms_agree')
    agree.setAutoDefault(False)
    agree.clicked.connect(dialog.accept)
    buttons.addWidget(decline)
    buttons.addWidget(agree)
    layout.addLayout(buttons)
    decline.setFocus()
    return dialog.exec() == QDialog.DialogCode.Accepted
