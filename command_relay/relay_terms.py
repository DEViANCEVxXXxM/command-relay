# SPDX-License-Identifier: Apache-2.0
"""Startup locale foundation and acknowledgement of the distributed notice."""
from pathlib import Path


LANGUAGES = {'en': 'English', 'ru': 'Русский'}
DEFAULT_LANGUAGE = 'en'
_MESSAGES = {
    'en': {'terms_title': 'Command Relay — Disclaimer',
           'terms_heading': 'Review the risks before continuing',
           'terms_decline': 'Decline and exit', 'terms_agree': 'I understand and agree',
           'language_saved': 'Startup language saved. It applies next time you start Command Relay. The workbench is still in English.'},
    'ru': {'terms_title': 'Command Relay — Отказ от ответственности',
           'terms_heading': 'Ознакомьтесь с рисками перед продолжением',
           'terms_decline': 'Отказаться и выйти', 'terms_agree': 'Понимаю и принимаю',
           'language_saved': 'Язык запуска сохранён. Изменение вступит в силу при следующем запуске Command Relay. Рабочий интерфейс пока на английском.'},
}


def saved_language(settings):
    value = settings.get('language')
    return value if isinstance(value, str) and value in LANGUAGES else None


def tr(key, language=DEFAULT_LANGUAGE):
    """Stable message IDs; missing translations fall back to English, not raw IDs."""
    return _MESSAGES.get(language, _MESSAGES[DEFAULT_LANGUAGE]).get(key, _MESSAGES[DEFAULT_LANGUAGE][key])


def startup_language(settings, choose, confirm, persist):
    """No workbench or preference write before explicit notice acceptance."""
    previous = saved_language(settings)
    selected = previous if previous is not None else choose()
    if not isinstance(selected, str) or selected not in LANGUAGES or not confirm(selected):
        return None
    if selected != previous:
        persist(selected)
    return selected


def choose_language(current=None, parent=None):
    from PySide6.QtWidgets import QInputDialog
    codes = list(LANGUAGES)
    label, accepted = QInputDialog.getItem(
        parent, 'Command Relay — Language / Язык',
        'Choose startup language / Выберите язык запуска\nWorkbench UI is currently English.',
        list(LANGUAGES.values()), codes.index(current) if current in codes else 0, False)
    if not accepted:
        return None
    return next((code for code, name in LANGUAGES.items() if name == label), None)


def disclaimer_text(root: Path, language=None) -> str:
    """Fail closed if the distributed notice is absent or empty."""
    text = (root / 'DISCLAIMER.md').read_text(encoding='utf-8').strip()
    if not text:
        raise ValueError('DISCLAIMER.md is empty; restore the original distribution.')
    if language is None:
        return text
    if language not in LANGUAGES:
        raise ValueError('Unsupported notice language')
    # Use the complete existing legal notice, not a translated summary.
    _, en_marker, remainder = text.partition('\n## English\n')
    english, ru_marker, russian = remainder.partition('\n## Русский\n')
    if not en_marker or not ru_marker or not english.strip() or not russian.strip():
        raise ValueError('Distributed bilingual notice is incomplete')
    return (english if language == 'en' else russian).strip()


def confirm_usage_terms(root: Path, language=DEFAULT_LANGUAGE) -> bool:
    # Keep Qt imports local so documentation checks work without GUI dependencies.
    from PySide6.QtWidgets import (
        QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
    )

    dialog = QDialog()
    dialog.setWindowTitle(tr('terms_title', language))
    dialog.resize(760, 600)
    layout = QVBoxLayout(dialog)
    heading = QLabel(tr('terms_heading', language))
    heading.setWordWrap(True)
    layout.addWidget(heading)
    notice = QPlainTextEdit()
    notice.setPlainText(disclaimer_text(root, language))
    notice.setReadOnly(True)
    layout.addWidget(notice, 1)
    buttons = QHBoxLayout()
    buttons.addStretch()
    decline = QPushButton(tr('terms_decline', language))
    decline.setObjectName('terms_decline')
    decline.setDefault(True)
    decline.clicked.connect(dialog.reject)
    agree = QPushButton(tr('terms_agree', language))
    agree.setObjectName('terms_agree')
    agree.setAutoDefault(False)
    agree.clicked.connect(dialog.accept)
    buttons.addWidget(decline)
    buttons.addWidget(agree)
    layout.addLayout(buttons)
    decline.setFocus()
    return dialog.exec() == QDialog.DialogCode.Accepted
