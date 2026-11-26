# SPDX-License-Identifier: Apache-2.0
"""Startup locale foundation and acknowledgement of the distributed notice."""
from pathlib import Path


# Only languages with an accepted full notice may enter the startup chooser.
# Planned locales are metadata, not enabled translations.
LOCALE_REGISTRY = {
    'en': ('English', 'ltr'), 'ru': ('Русский', 'ltr'),
    'zh-Hans': ('简体中文', 'ltr'), 'zh-Hant': ('繁體中文', 'ltr'),
    'ja': ('日本語', 'ltr'), 'ko': ('한국어', 'ltr'),
    'de': ('Deutsch', 'ltr'), 'fr': ('Français', 'ltr'),
    'es': ('Español', 'ltr'), 'pt-BR': ('Português (Brasil)', 'ltr'),
    'it': ('Italiano', 'ltr'), 'tr': ('Türkçe', 'ltr'),
    'ar': ('العربية', 'rtl'), 'hi': ('हिन्दी', 'ltr'),
    'uk': ('Українська', 'ltr'), 'uz': ('Oʻzbekcha', 'ltr'),
    'pl': ('Polski', 'ltr'),
}
LANGUAGES = {code: LOCALE_REGISTRY[code][0] for code in ('en', 'ru')}


def locale_direction(code):
    return LOCALE_REGISTRY.get(code, ('', 'ltr'))[1] if isinstance(code, str) else 'ltr'

DEFAULT_LANGUAGE = 'en'
MODES = ('casual', 'advanced')
DEFAULT_MODE = 'advanced'


def saved_mode(settings):
    value = settings.get('mode')
    return value if isinstance(value, str) and value in MODES else None


def startup_mode(settings, choose):
    """Existing valid preference bypasses the chooser; cancellation stays cancellation."""
    mode = saved_mode(settings)
    if mode is not None:
        return mode
    selected = choose()
    return selected if isinstance(selected, str) and selected in MODES else None


def sidebar_preference(settings, mode):
    key = 'show_sidebar_casual' if mode == 'casual' else 'show_sidebar'
    return settings.get(key, mode != 'casual') is True

_MESSAGES = {
    'en': {'terms_title': 'Command Relay — Disclaimer',
           'terms_heading': 'Review the risks before continuing',
           'reduced_motion': 'Reduced motion',
           'terms_decline': 'Decline and exit', 'terms_agree': 'I understand and agree',
           'language_saved': 'Language saved. It applies next time you start Command Relay. Some tools and confirmation dialogs are still in English.'},
    'ru': {'terms_title': 'Command Relay — Отказ от ответственности',
           'terms_heading': 'Ознакомьтесь с рисками перед продолжением',
           'reduced_motion': 'Уменьшить анимацию',
           'terms_decline': 'Отказаться и выйти', 'terms_agree': 'Понимаю и принимаю',
           'language_saved': 'Язык сохранён. Изменение вступит в силу при следующем запуске Command Relay. Некоторые инструменты и диалоги подтверждения пока на английском.'},
}


# Mode selection is bilingual; raw scripts, report data and IDs remain untouched.
_MESSAGES['en'].update({
    'mode_title': 'Choose your workspace', 'mode_heading': 'Same execution engine. Two ways to work.',
    'mode_casual': 'Casual', 'mode_advanced': 'Advanced',
    'mode_casual_desc': 'Import, review, run and copy results. Less visual clutter.',
    'mode_advanced_desc': 'Full workbench with steps, outline and script library.',
    'mode_safety': 'Both modes keep command review, safety settings and explicit Run.',
    'mode_continue': 'Continue', 'mode_cancel': 'Cancel', 'mode_settings': 'Workspace mode…', 'light_theme': 'Light theme',
})
_MESSAGES['ru'].update({
    'mode_title': 'Выберите рабочий режим', 'mode_heading': 'Один движок выполнения. Два режима работы.',
    'mode_casual': 'Casual', 'mode_advanced': 'Advanced',
    'mode_casual_desc': 'Импорт, проверка, запуск и копирование результата. Меньше лишних элементов.',
    'mode_advanced_desc': 'Полный интерфейс с шагами, структурой команд и библиотекой скриптов.',
    'mode_safety': 'В обоих режимах сохраняются проверка команд, настройки безопасности и явный запуск.',
    'mode_continue': 'Продолжить', 'mode_cancel': 'Отмена', 'mode_settings': 'Режим работы…', 'light_theme': 'Светлая тема',
})

# Shared workbench catalog. IDs are stable; never translate raw task/report content.
_WORKBENCH = {
    'more': ('More', 'Ещё'),
    'more_tip': ('Project tools, reports and settings', 'Инструменты проекта, отчёты и настройки'),
    'workspace': ('WORKSPACE', 'РАБОЧАЯ ПАПКА'),
    'browse': ('Browse', 'Обзор'),
    'profiles': ('Profiles', 'Профили'),
    'open_file': ('Open file', 'Открыть файл'),
    'paste_ai': ('Paste / AI task', 'Вставить / AI-задача'),
    'stop': ('■ Stop', '■ Стоп'),
    'run_commands': ('▶ Run commands', '▶ Выполнить команды'),
    'run_tip': ('Run (Ctrl+Enter). Review the script and workspace first; identical task history is checked before execution. Commands use your account permissions.', 'Запуск (Ctrl+Enter). Сначала проверьте сценарий и рабочую папку; перед выполнением проверяется история одинаковых задач. Команды выполняются с правами вашей учётной записи.'),
    'casual_flow': ('01  IMPORT     →     02  REVIEW     →     03  RUN     →     04  COPY RESULT', '01  ИМПОРТ     →     02  ПРОВЕРКА     →     03  ЗАПУСК     →     04  КОПИЯ РЕЗУЛЬТАТА'),
    'casual_accessible': ('Import, review, run, copy result', 'Импорт, проверка, запуск, копирование результата'),
    'live_output': ('LIVE OUTPUT (visible tail)', 'ТЕКУЩИЙ ВЫВОД (видимая часть)'),
    'outline': ('COMMAND OUTLINE', 'СТРУКТУРА КОМАНД'),
    'steps': ('Steps', 'Шаги'),
    'library_heading': ('SCRIPT LIBRARY', 'БИБЛИОТЕКА СЦЕНАРИЕВ'),
    'folder_ellipsis': ('Folder…', 'Папка…'),
    'refresh': ('Refresh', 'Обновить'),
    'filter_scripts': ('Filter scripts', 'Фильтр сценариев'),
    'load_selected': ('Load selected', 'Загрузить выбранное'),
    'save_editor': ('Save editor as…', 'Сохранить сценарий как…'),
    'scripts': ('Scripts', 'Сценарии'),
    'commands_initial': ('COMMANDS  /  Untitled', 'КОМАНДЫ  /  Без названия'),
    'editor_placeholder': ('Drop a task file here or use Paste / AI task.', 'Перетащите файл задачи сюда или нажмите «Вставить / AI-задача».'),
    'terminal_initial': ('TERMINAL  /  No report', 'ТЕРМИНАЛ  /  Нет отчёта'),
    'dense': ('Dense', 'Компактно'),
    'wrap': ('Wrap', 'Перенос'),
    'follow': ('Follow', 'Следить'),
    'find': ('Find', 'Найти'),
    'find_output': ('Find in visible output', 'Поиск в видимом выводе'),
    'import_hint': ('Drop a script or import an AI task.', 'Перетащите сценарий или импортируйте AI-задачу.'),
    'history': ('History', 'История'),
    'working_directory': ('Working directory', 'Рабочая папка'),
    'command_editor': ('Command editor', 'Редактор команд'),
    'terminal_accessible': ('Read-only terminal output', 'Вывод терминала только для чтения'),
    'execution_steps': ('Execution steps', 'Этапы выполнения'),
    'command_outline': ('Command outline', 'Структура команд'),
    'script_library': ('Script library', 'Библиотека сценариев'),
    'sidebar': ('Workbench sidebar', 'Боковая панель'),
    'status_accessible': ('Task and export status', 'Состояние задачи и экспорта'),
    'inspector_accessible': ('Task Inspector result', 'Результат инспекции задачи'),
    'more_accessible': ('More tools', 'Другие инструменты'),
    'run_accessible': ('Run commands', 'Выполнить команды'),
    'stop_accessible': ('Stop execution', 'Остановить выполнение'),
    'previous_match': ('Find previous match (Shift+F3)', 'Предыдущее совпадение (Shift+F3)'),
    'next_match': ('Find next match (F3)', 'Следующее совпадение (F3)'),
    'close_search': ('Close output search', 'Закрыть поиск'),
    'follow_desc': ('Automatically scroll terminal output to the latest line.', 'Автоматически прокручивать терминал до последней строки.'),
    'editor_desc': ('Review imported commands before running. Ctrl+Enter requests execution.', 'Проверьте импортированные команды перед запуском. Ctrl+Enter запрашивает выполнение.'),
    'output_desc': ('Visible tail of the report. Use Copy or History for the complete report.', 'Видимая часть отчёта. Для полного отчёта используйте «Копировать» или «История».'),
    'copy_session': ('Copy session context', 'Копировать контекст сеанса'),
    'clear_editor': ('Clear editor', 'Очистить редактор'),
    'project': ('Project', 'Проект'),
    'project_context': ('Project context', 'Контекст проекта'),
    'ai_context': ('AI context…', 'AI-контекст…'),
    'git_dashboard': ('Git dashboard', 'Панель Git'),
    'github_prs': ('GitHub pull requests…', 'Pull requests GitHub…'),
    'reports': ('Reports', 'Отчёты'),
    'copy_ai': ('Copy AI result (masked)', 'Копировать AI-результат (маскирование)'),
    'copy_compact': ('Copy compact text (masked)', 'Копировать краткий текст (маскирование)'),
    'copy_raw': ('Copy full report (RAW, unmasked)', 'Копировать полный отчёт (RAW, без маскирования)'),
    'metrics_latest': ('Metrics — latest', 'Последние метрики'),
    'open_latest': ('Open latest', 'Открыть последний'),
    'folder': ('Folder', 'Папка'),
    'queue': ('Task queue…', 'Очередь задач…'),
    'sha_file': ('SHA-256 file…', 'SHA-256 файла…'),
    'settings': ('Settings', 'Настройки'),
    'safety_settings': ('Safety settings…', 'Настройки безопасности…'),
    'updates': ('Updates…', 'Обновления…'),
    'language_settings': ('Startup language… / Язык запуска…', 'Язык интерфейса… / Language…'),
    'show_sidebar': ('Show sidebar', 'Показать боковую панель'),
    'wrap_output': ('Wrap output', 'Перенос строк вывода'),
    'dense_output': ('Dense output', 'Компактный вывод'),
    'find_in_output': ('Find in output', 'Поиск в выводе'),
    'open_task': ('Open task', 'Открыть задачу'),
    'paste_task': ('Paste task', 'Вставить задачу'),
    'run_short': ('▶ Run', '▶ Запуск'),
    'restoring': ('Restoring previous report…', 'Восстановление предыдущего отчёта…'),
    'terminal_previous': ('TERMINAL  /  latest.txt (previous run)', 'ТЕРМИНАЛ  /  latest.txt (предыдущий запуск)'),
    'restored': ('Previous report restored.', 'Предыдущий отчёт восстановлен.'),
    'copy': ('Copy', 'Копировать'),
    'copy_accessible': ('Copy report — AI result by default', 'Копировать отчёт — по умолчанию AI-результат'),
    'imported': ('Task imported; review before running', 'Задача импортирована; проверьте перед запуском'),
    'start_failed': ('FAILED / START ERROR', 'ОШИБКА / НЕ УДАЛОСЬ ЗАПУСТИТЬ'),
    'ready': ('READY  |  PowerShell  |  UTF-8', 'ГОТОВО  |  PowerShell  |  UTF-8'),
    'running': ('RUNNING  |  0s  |  Full log on disk', 'ВЫПОЛНЕНИЕ  |  0 с  |  Полный журнал на диске'),
    'stopping': ('STOPPING  |  Waiting for process termination', 'ОСТАНОВКА  |  Ожидание завершения процесса'),
    'commands_prefix': ('COMMANDS  /  ', 'КОМАНДЫ  /  '),
    'terminal_prefix': ('TERMINAL  /  ', 'ТЕРМИНАЛ  /  '),
    'copy_tip': ('Click: Copy AI (best-effort secret masking)\nShift + click: Copy text (masked)\nCtrl + click: Copy RAW full report (unmasked)\nCtrl takes priority if both are held.', 'Щелчок: AI-результат (маскирование секретов без гарантий)\nShift + щелчок: текст (маскирование)\nCtrl + щелчок: полный RAW-отчёт (без маскирования)\nПри одновременном нажатии приоритет у Ctrl.'),
    'window_title': ('Command Relay {version} — Qt Workbench', 'Command Relay {version} — Рабочая область'),
    'clock_running': ('RUNNING', 'ВЫПОЛНЕНИЕ'),
    'clock_stopping': ('STOPPING', 'ОСТАНОВКА'),
    'clock_log': ('Full log on disk', 'Полный журнал на диске'),
}
for _key, (_english, _russian) in _WORKBENCH.items():
    _MESSAGES['en'][_key] = _english
    _MESSAGES['ru'][_key] = _russian


# Dialog presentation, separate from raw diagnostics and protocol values.
_DIALOG_MESSAGES = {
    'update_title': ('Updates', 'Обновления'),
    'update_current': ('Current version: ', 'Текущая версия: '),
    'update_intro': ('Check official GitHub releases, verify a package, or prepare an external updater. Nothing is installed in this dialog.', 'Проверьте официальные релизы GitHub, подлинность пакета или подготовьте внешнюю программу обновления. В этом окне ничего не устанавливается.'),
    'update_latest_initial': ('Latest stable release: Not checked', 'Последний стабильный релиз: не проверен'),
    'update_start': ('Select Check for updates to start.', 'Нажмите «Проверить обновления», чтобы начать.'),
    'update_unverified': ('Publisher signature: Not verified', 'Подпись издателя: не проверена'),
    'update_check': ('Check for updates', 'Проверить обновления'),
    'update_verify': ('Download & Verify', 'Скачать и проверить'),
    'dialog_close': ('Close', 'Закрыть'),
    'update_prepare': ('Prepare installation…', 'Подготовить установку…'),
    'update_checking': ('Latest stable release: Checking…', 'Последний стабильный релиз: проверка…'),
    'update_request': ('Requesting official release metadata…', 'Запрос метаданных официального релиза…'),
    'update_downloading': ('Downloading and verifying signed package…', 'Загрузка и проверка подписанного пакета…'),
    'update_latest': ('Latest stable release: ', 'Последний стабильный релиз: '),
    'update_unavailable': ('Unavailable', 'Недоступен'),
    'update_digest': ('Verified archive SHA-256: ', 'SHA-256 проверенного архива: '),
    'update_original': ('Select the original signed release package folder', 'Выберите папку исходного подписанного пакета релиза'),
    'update_prepare_title': ('Prepare installation', 'Подготовка установки'),
    'update_prepare_confirm': ('Prepare the external updater and close Command Relay? Save or copy any unsaved editor content first. The current signed release package and an installation permission are required. The external terminal will ask separately before replacing files.', 'Подготовить внешнюю программу обновления и закрыть Command Relay? Сначала сохраните или скопируйте несохранённое содержимое редактора. Необходимы текущий подписанный пакет релиза и разрешение на установку. Перед заменой файлов внешний терминал запросит отдельное подтверждение.'),
    'update_prepare_failed': ('Unable to prepare updater. Preserve any partial bundle.', 'Не удалось подготовить программу обновления. Сохраните все частично подготовленные файлы.'),
    'safety_title': ('Safety settings', 'Настройки безопасности'),
    'safety_default': ('Automation permissions — disabled by default', 'Разрешения автоматизации — по умолчанию отключены'),
    'safety_intro': ('Built-in merge and update installation permissions are separate. Manual Run and manual merge remain separate. Arbitrary scripts are not sandboxed.', 'Разрешения встроенного слияния и установки обновлений независимы. Ручной запуск и ручное слияние остаются отдельными действиями. Произвольные сценарии выполняются без изолированной песочницы.'),
    'safety_workspace': ('Workspace: ', 'Рабочая папка: '),
    'safety_refresh_hint': ('Refresh to read local policy and origin.', 'Обновите данные, чтобы прочитать локальную политику и origin.'),
    'safety_merge': ('Allow automatic squash merge for this workspace and repository', 'Разрешить автоматическое squash-слияние для этой рабочей папки и репозитория'),
    'safety_merge_accessible': ('Allow scoped automatic squash merge', 'Разрешить автоматическое squash-слияние в заданной области'),
    'safety_review': ('Every automatic merge still requires explicit task review.', 'Каждое автоматическое слияние по-прежнему требует явной проверки задачи.'),
    'safety_installation': ('Installation: ', 'Установка: '),
    'safety_update': ('Allow signed update installation for this application', 'Разрешить установку подписанных обновлений для этого приложения'),
    'safety_update_accessible': ('Allow installation of signed updates', 'Разрешить установку подписанных обновлений'),
    'safety_terminal': ('Separate terminal confirmation is still required. No automatic download, install or restart from this setting.', 'По-прежнему требуется отдельное подтверждение в терминале. Эта настройка не выполняет автоматическую загрузку, установку или перезапуск.'),
    'safety_update_apply': ('Apply update permission…', 'Применить разрешение на обновление…'),
    'safety_refresh': ('Refresh', 'Обновить'),
    'safety_history': ('History…', 'История…'),
    'safety_revoke_all': ('Revoke all grants…', 'Отозвать все разрешения…'),
    'safety_apply': ('Apply change…', 'Применить изменение…'),
    'safety_busy': ('Reading or saving local policy…', 'Чтение или сохранение локальной политики…'),
    'safety_repository': ('\nRepository: ', '\nРепозиторий: '),
    'safety_unresolved': ('Not resolved', 'Не определён'),
    'safety_eligible': (' — eligible for permission changes', ' — изменение разрешения доступно'),
    'safety_unavailable': (' — update permission unavailable', ' — разрешение на обновление недоступно'),
    'safety_history_title': ('Permission history', 'История разрешений'),
    'safety_history_accessible': ('Local permission history', 'Локальная история разрешений'),
    'safety_confirm': ('Confirm permission change', 'Подтверждение изменения разрешения'),
    'safety_no_change': ('No permission change selected.', 'Изменение разрешения не выбрано.'),
    'safety_no_update_change': ('No update permission change selected.', 'Изменение разрешения на обновление не выбрано.'),
    'safety_revoke_confirm': ('Revoke all saved automation grants for all workspaces?', 'Отозвать все сохранённые разрешения автоматизации для всех рабочих папок?'),
    'confirm_yes': ('Yes', 'Да'),
    'confirm_cancel': ('Cancel', 'Отмена'),
    'review_commands': ('Review commands', 'Проверка команд'),
    'review_risk_intro': ('The script matches potentially risky command patterns:\n\n', 'В сценарии обнаружены потенциально рискованные шаблоны команд:\n\n'),
    'review_risk_end': ('\n\nReview the script and workspace. This is not a safety verdict. Run anyway?', '\n\nПроверьте сценарий и рабочую папку. Это не заключение о безопасности. Всё равно выполнить?'),
    'repeat_title': ('Review previous execution', 'Проверка предыдущего выполнения'),
    'repeat_report': ('A matching task was previously run in this workspace.\n\nReport: ', 'Совпадающая задача ранее выполнялась в этой рабочей папке.\n\nОтчёт: '),
    'repeat_verdict': ('\nAssertions / run status: ', '\nПроверки / статус выполнения: '),
    'repeat_exit': ('\nProcess exit: ', '\nКод завершения процесса: '),
    'repeat_unknown': ('Previous execution could not be fully checked.', 'Не удалось полностью проверить предыдущее выполнение.'),
    'repeat_warning': ('\n\nMatching history does not prove the current environment or effects are unchanged. Review before running again.', '\n\nСовпадение истории не доказывает, что окружение или последствия не изменились. Проверьте задачу перед повторным запуском.'),
    'repeat_run': ('Run anyway', 'Всё равно выполнить'),
    'stop_title': ('Stop', 'Остановка'),
    'stop_confirm': ('Terminate the running process tree? This does not undo changes.', 'Завершить дерево выполняющихся процессов? Это не отменяет внесённые изменения.'),
    'merge_allow': ('Allow automatic squash merge?\n\n{workspace}\n{repository}\n\nNo merge will be executed now.', 'Разрешить автоматическое squash-слияние?\n\n{workspace}\n{repository}\n\nСлияние сейчас выполняться не будет.'),
    'merge_revoke': ('Revoke automatic squash merge?\n\n{workspace}\n{repository}\n\nNo merge will be executed now.', 'Отозвать разрешение на автоматическое squash-слияние?\n\n{workspace}\n{repository}\n\nСлияние сейчас выполняться не будет.'),
    'install_allow': ('Allow signed update installation?\n\n{root}\n\nInstallation still requires explicit terminal confirmation. No update will be executed now.', 'Разрешить установку подписанных обновлений?\n\n{root}\n\nУстановка по-прежнему требует явного подтверждения в терминале. Обновление сейчас выполняться не будет.'),
    'install_revoke': ('Revoke signed update installation?\n\n{root}\n\nInstallation still requires explicit terminal confirmation. No update will be executed now.', 'Отозвать разрешение на установку подписанных обновлений?\n\n{root}\n\nУстановка по-прежнему требует явного подтверждения в терминале. Обновление сейчас выполняться не будет.'),
    'update_check_failed': ('Release check failed. Retry later.', 'Не удалось проверить релиз. Повторите попытку позже.'),
    'update_verified': ('Publisher signature: Verified', 'Подпись издателя: проверена'),
    'update_retained': ('Package verified and retained in memory until this dialog closes. No installation performed.', 'Пакет проверен и сохранён в памяти до закрытия этого окна. Установка не выполнялась.'),
    'update_verify_failed': ('Package verification failed. Retry or check again.', 'Не удалось проверить пакет. Повторите проверку или запрос релиза.'),
    'update_newer': ('Newer release available.', 'Доступен более новый релиз.'),
    'update_same': ('Current version is up to date.', 'Установлена актуальная версия.'),
    'update_older': ('Published stable release is older than this build.', 'Опубликованный стабильный релиз старше этой сборки.'),
    'update_missing_signature': ('Signature assets missing. Signed installation unavailable.', 'Файлы подписи отсутствуют. Установка подписанного пакета недоступна.'),
    'update_listed_signature': ('Signature assets listed. Publisher signature NOT verified.', 'Файлы подписи перечислены. Подпись издателя НЕ проверена.'),
    'safety_failed': ('Policy operation not verified. Refresh; if invalid or locked, inspect the local policy file before making changes.', 'Операция с политикой не подтверждена. Обновите данные; если политика недействительна или заблокирована, проверьте локальный файл политики перед изменениями.'),
    'safety_worker_failed': ('Could not start local worker.', 'Не удалось запустить локальный рабочий поток.'),
    'safety_no_origin': ('No supported GitHub origin. You can still revoke all saved grants.', 'Поддерживаемый GitHub origin не найден. Вы всё ещё можете отозвать все сохранённые разрешения.'),
    'safety_loaded': ('Local policy loaded. No changes made.', 'Локальная политика загружена. Изменений нет.'),
    'safety_cancelled': ('Cancelled. No changes made.', 'Отменено. Изменений нет.'),
    'safety_saved': ('Permission saved. No commands or network writes executed.', 'Разрешение сохранено. Команды и сетевые операции записи не выполнялись.'),
    'safety_update_saved': ('Update permission saved. No update or network operation executed.', 'Разрешение на обновление сохранено. Обновление и сетевые операции не выполнялись.'),
    'safety_revoked': ('All grants revoked.', 'Все разрешения отозваны.'),
}
for _key, (_english, _russian) in _DIALOG_MESSAGES.items():
    _MESSAGES['en'][_key] = _english
    _MESSAGES['ru'][_key] = _russian

_DIALOG_RESULTS = {
    _DIALOG_MESSAGES['update_check_failed'][0]: 'update_check_failed',
    _DIALOG_MESSAGES['update_verified'][0]: 'update_verified',
    _DIALOG_MESSAGES['update_retained'][0]: 'update_retained',
    _DIALOG_MESSAGES['update_verify_failed'][0]: 'update_verify_failed',
    _DIALOG_MESSAGES['update_newer'][0]: 'update_newer',
    _DIALOG_MESSAGES['update_same'][0]: 'update_same',
    _DIALOG_MESSAGES['update_older'][0]: 'update_older',
    _DIALOG_MESSAGES['update_missing_signature'][0]: 'update_missing_signature',
    _DIALOG_MESSAGES['update_listed_signature'][0]: 'update_listed_signature',
    _DIALOG_MESSAGES['safety_failed'][0]: 'safety_failed',
    _DIALOG_MESSAGES['safety_worker_failed'][0]: 'safety_worker_failed',
    _DIALOG_MESSAGES['safety_no_origin'][0]: 'safety_no_origin',
    _DIALOG_MESSAGES['safety_loaded'][0]: 'safety_loaded',
    _DIALOG_MESSAGES['safety_cancelled'][0]: 'safety_cancelled',
    _DIALOG_MESSAGES['safety_saved'][0]: 'safety_saved',
    _DIALOG_MESSAGES['safety_update_saved'][0]: 'safety_update_saved',
    _DIALOG_MESSAGES['safety_revoked'][0]: 'safety_revoked',
    _DIALOG_MESSAGES['update_unverified'][0]: 'update_unverified',
}

def dialog_result_text(message, language=DEFAULT_LANGUAGE):
    """Translate only known UI-owned worker messages, not arbitrary diagnostics."""
    key = _DIALOG_RESULTS.get(message)
    return tr(key, language) if key is not None else message


def saved_language(settings):
    value = settings.get('language')
    return value if isinstance(value, str) and value in LANGUAGES else None


# Casual presentation is a projection of actual editor/process/report state.
_CASUAL_MESSAGES = {
    'casual_import': ('01  Import', '01  Импорт'),
    'casual_review': ('02  Review', '02  Проверка'),
    'casual_run': ('03  Run', '03  Запуск'),
    'casual_result': ('04  Result', '04  Результат'),
    'casual_empty': ('No task loaded', 'Задача не загружена'),
    'casual_edited': ('Edited commands', 'Изменённые команды'),
    'casual_untitled': ('Untitled commands', 'Команды без названия'),
    'casual_import_help': ('Drop a file in the editor, open a task or paste commands.', 'Перетащите файл в редактор, откройте задачу или вставьте команды.'),
    'casual_review_help': ('Review the actual commands and workspace. Run requires your action.', 'Проверьте команды и рабочую папку. Запуск требует вашего действия.'),
    'casual_running_help': ('Execution in progress. See live output below.', 'Выполняется задача. Текущий вывод находится ниже.'),
    'casual_result_help': ('Report saved. Inspect the output or copy the result. Exit status is not a test verdict.', 'Отчёт сохранён. Проверьте вывод или скопируйте результат. Код выхода не является результатом тестов.'),
    'casual_title_accessible': ('Current task summary', 'Сводка текущей задачи'),
    'casual_stage_accessible': ('Current workflow stage: {stage}', 'Текущий этап: {stage}'),
}
for _key, (_english, _russian) in _CASUAL_MESSAGES.items():
    _MESSAGES['en'][_key] = _english
    _MESSAGES['ru'][_key] = _russian


def casual_stage(has_script, running, report_ready):
    if running:
        return 'run'
    if report_ready:
        return 'result'
    return 'review' if has_script else 'import'


def casual_task_title(task, source, *, has_script, edited, language='en'):
    if not has_script:
        return tr('casual_empty', language)
    if edited:
        return tr('casual_edited', language)
    title = task.get('title') or task.get('task_id') or source
    if not isinstance(title, str) or title == 'Untitled':
        return tr('casual_untitled', language)
    # Bounded plain-text metadata is a label, never a command or rich text.
    title = ' '.join(title.split())[:100]
    return title or tr('casual_untitled', language)


# GitHub presentation only: stable statuses, identifiers and exported packets stay raw.
_GITHUB_MESSAGES = {
    'gh_title': ('GitHub pull requests', 'Pull requests GitHub'),
    'gh_intro': ('Optional GitHub CLI integration · no automatic writes', 'Необязательная интеграция GitHub CLI · без автоматических изменений'),
    'gh_repository': ('Repository', 'Репозиторий'),
    'gh_origin': ('Use workspace origin', 'Использовать origin'),
    'gh_refresh': ('Refresh open PRs', 'Обновить список PR'),
    'gh_pull_request': ('Pull request', 'Pull request'),
    'gh_number': ('Enter PR number or select from list', 'Введите номер PR или выберите из списка'),
    'gh_inspect': ('Inspect / refresh', 'Проверить / обновить'),
    'gh_detail': ('Select a repository and PR, then inspect its current status.', 'Выберите репозиторий и PR, затем проверьте текущее состояние.'),
    'gh_ready': ('Ready to detect workspace origin.', 'Можно определить origin рабочей папки.'),
    'gh_merge': ('Squash and merge…', 'Выполнить squash merge…'),
    'gh_review_copy': ('Review / copy status', 'Проверить / копировать статус'),
    'gh_close': ('Close', 'Закрыть'),
    'gh_working': ('Working…', 'Выполняется…'),
    'gh_worker_failed': ('Could not start worker.', 'Не удалось запустить фоновую операцию.'),
    'gh_invalid_number': ('Enter a positive pull request number.', 'Введите положительный номер PR.'),
    'gh_merge_unverified': ('Merge not verified. Refresh the PR before any further action. No retry or branch deletion was attempted.', 'Слияние не подтверждено. Обновите PR перед любым дальнейшим действием. Повторная попытка и удаление ветки не выполнялись.'),
    'gh_origin_detected': ('Repository detected. Refresh open PRs or enter a PR number.', 'Репозиторий найден. Обновите список открытых PR или введите номер.'),
    'gh_list_count': ('{count} open PRs loaded.', 'Загружено открытых PR: {count}.'),
    'gh_list_limit': (' List limited to 100; enter a PR number to inspect another.', ' Список ограничен 100 PR; для проверки другого введите его номер.'),
    'gh_list_select': (' Select and inspect a PR.', ' Выберите и проверьте PR.'),
    'gh_snapshot': ('Review the snapshot. GitHub server policies remain authoritative.', 'Проверьте снимок состояния. Правила сервера GitHub остаются обязательными.'),
    'gh_merge_verified': ('Merge verified. Remote branch cleanup is left to GitHub automatic deletion settings or manual review. No local checkout or deletion.', 'Слияние подтверждено. Удаление удалённой ветки зависит от настроек GitHub или ручной проверки. Локальная ветка не переключалась и не удалялась.'),
    'gh_confirm_title': ('Confirm squash merge', 'Подтвердите squash merge'),
    'gh_confirm_action': ('Squash and merge', 'Выполнить squash merge'),
    'gh_confirm_body': ('{repo} · PR #{number}\n{title}\n\n{head} → {base}\nHead SHA: {head_sha}\nBase SHA: {base_sha}\n\nThis writes to GitHub. The reviewed snapshot will be revalidated. No admin bypass or branch deletion.', '{repo} · PR #{number}\n{title}\n\n{head} → {base}\nHead SHA: {head_sha}\nBase SHA: {base_sha}\n\nЭто изменит данные на GitHub. Проверенный снимок будет проверен повторно. Без обхода ограничений администратора и удаления веток.'),
    'gh_export_failed': ('Could not prepare protected export; nothing copied.', 'Не удалось подготовить защищённый экспорт; ничего не скопировано.'),
    'gh_review_json': ('Review GitHub status JSON', 'Проверьте JSON статуса GitHub'),
    'gh_mask_warning': ('Best-effort masking only. Review before copying or sharing.', 'Маскирование не гарантирует конфиденциальность. Проверьте данные перед копированием или отправкой.'),
    'gh_copy_json': ('Copy JSON', 'Копировать JSON'),
    'gh_cancel': ('Cancel', 'Отмена'),
    'gh_state': ('State at inspection: ', 'Состояние при проверке: '),
    'gh_observed': ('Observed UTC: ', 'Время проверки UTC: '),
    'gh_checks': ('Checks:', 'Проверки:'),
    'gh_readiness': ('Readiness at inspection: ', 'Готовность при проверке: '),
    'gh_readiness_yes': ('READY (server rules still apply)', 'ГОТОВ (правила сервера действуют)'),
    'gh_readiness_no': ('BLOCKED', 'ЗАБЛОКИРОВАН'),
    'gh_outcome': ('Merge outcome: ', 'Результат слияния: '),
    'gh_verified_sha': ('Verified merge SHA: ', 'Подтверждённый SHA слияния: '),
}
for _key, (_english, _russian) in _GITHUB_MESSAGES.items():
    _MESSAGES['en'][_key] = _english
    _MESSAGES['ru'][_key] = _russian


_RESULT_MESSAGES = {
    'result_busy': ('Finish the current run or copy first', 'Сначала завершите текущий запуск или копирование'),
    'result_workspace': ('Select a valid workspace', 'Выберите действительную рабочую папку'),
    'result_session_prepare': ('Preparing session context…', 'Подготовка контекста сессии…'),
    'result_session_title': ('Workspace session context', 'Контекст рабочей сессии'),
    'result_wait': ('Wait for completion or choose a historical report', 'Дождитесь завершения или выберите отчёт из истории'),
    'result_no_report': ('No report selected', 'Отчёт не выбран'),
    'result_copy_busy': ('Preparing previous copy…', 'Подготовка предыдущего копирования…'),
    'result_tool_busy': ('Another local tool is running', 'Уже выполняется другой локальный инструмент'),
    'result_mask': ('Best-effort masking applied. Review before copying or saving; no automatic sharing.', 'Применено маскирование без гарантии полноты. Проверьте данные перед копированием или сохранением; автоматической отправки нет.'),
    'result_copy_json': ('Copy JSON', 'Копировать JSON'),
    'result_save_local': ('Save local JSON', 'Сохранить локальный JSON'),
    'result_save_json': ('Save JSON…', 'Сохранить JSON…'),
    'result_close': ('Close', 'Закрыть'),
    'result_queue': ('Task queue — manual', 'Очередь задач — ручная'),
    'result_queue_notice': ('Session queue only. Loading a task never runs it or changes workspace.', 'Очередь только для текущей сессии. Загрузка задачи не запускает её и не меняет рабочую папку.'),
    'result_add_tasks': ('Add tasks', 'Добавить задачи'),
    'result_replace': ('Replace editor?', 'Заменить содержимое редактора?'),
    'result_load_question': ('Load selected task into editor?', 'Загрузить выбранную задачу в редактор?'),
    'result_add_tasks_button': ('Add tasks…', 'Добавить задачи…'),
    'result_load_selected': ('Load selected', 'Загрузить выбранную'),
    'result_remove': ('Remove', 'Удалить'),
    'result_completed': ('Choose a completed report', 'Выберите завершённый отчёт'),
    'result_metrics': ('Observed metrics', 'Наблюдаемые метрики'),
    'result_two_reports': ('Select two reports', 'Выберите два отчёта'),
    'result_compare_metrics_title': ('Compare metrics (old → new)', 'Сравнение метрик (старый → новый)'),
    'result_select_export': ('Select reports to export', 'Выберите отчёты для экспорта'),
    'result_export_reports': ('Export selected reports', 'Экспорт выбранных отчётов'),
    'result_evidence': ('Evidence bundle', 'Архив отчётов'),
    'result_history': ('Run history', 'История запусков'),
    'result_search': ('Search history', 'Поиск по истории'),
    'result_started': ('Started', 'Начало'),
    'result_command': ('Command', 'Команда'),
    'result_process_status': ('Process status', 'Статус процесса'),
    'result_elapsed': ('Elapsed', 'Время'),
    'result_loading': ('Loading history…', 'Загрузка истории…'),
    'result_review_session': ('Review workspace session…', 'Просмотр контекста сессии…'),
    'result_read_error': ('History could not be read; use Refresh or Reports > Folder.', 'Не удалось прочитать историю; обновите её или откройте папку отчётов.'),
    'result_one_report': ('Select one report', 'Выберите один отчёт'),
    'result_large_report': ('Large report: use external diff viewer', 'Большой отчёт: используйте внешний инструмент сравнения'),
    'result_too_many': ('Too many compact lines for inline comparison', 'Слишком много строк для встроенного сравнения'),
    'result_compact': ('Compact comparison', 'Компактное сравнение'),
    'result_no_diff': ('No differences', 'Нет различий'),
    'result_view_full': ('View full', 'Открыть полностью'),
    'result_compare_two': ('Compare 2', 'Сравнить два'),
    'result_metrics_button': ('Metrics', 'Метрики'),
    'result_compare_metrics': ('Compare metrics', 'Сравнить метрики'),
    'result_export_zip': ('Export ZIP', 'Экспорт ZIP'),
    'result_refresh': ('Refresh', 'Обновить'),
    'result_filter_0': ('All', 'Все'),
    'result_filter_1': ('Exit 0', 'Код выхода 0'),
    'result_filter_2': ('Failed', 'Ошибка процесса'),
    'result_filter_3': ('Cancelled', 'Отменено'),
    'result_filter_4': ('Partial / unknown', 'Частично / неизвестно'),
    'result_count': ('{count} reports', 'Отчётов: {count}'),
    'result_unreadable': (' | {count} unreadable', ' | Не прочитано: {count}'),
    'result_limited': (' | Limited history; older files remain in Reports folder.', ' | История ограничена; старые файлы остаются в папке отчётов.'),
}
for _key, (_english, _russian) in _RESULT_MESSAGES.items():
    _MESSAGES['en'][_key] = _english
    _MESSAGES['ru'][_key] = _russian


_RUNTIME_MESSAGES = {'runtime_workspace': ('Workspace', 'Рабочая папка'),
 'runtime_library': ('Script library', 'Библиотека скриптов'),
 'runtime_save_script': ('Save script', 'Сохранить скрипт'),
 'runtime_open_task': ('Open task or script', 'Открыть задачу или скрипт'),
 'runtime_loaded': ('Loaded ', 'Загружено: '),
 'runtime_loaded_tip': ('Loaded script: ', 'Загруженный скрипт: '),
 'runtime_review_high': ('⚠ Review commands', '⚠ Проверьте команды'),
 'runtime_review_effects': ('Review effects', 'Проверьте возможные последствия'),
 'runtime_copy_wait': ('Wait for Copied before starting another run',
                       'Дождитесь завершения копирования перед новым запуском'),
 'runtime_script_workspace': ('Enter a script and valid workspace',
                              'Введите скрипт и укажите действительную рабочую папку'),
 'runtime_valid_workspace': ('Select a valid workspace', 'Выберите действительную рабочую папку'),
 'runtime_saved': ('Saved ', 'Сохранено: '),
 'runtime_save_failed': ('Save failed: ', 'Ошибка сохранения: '),
 'runtime_hash_title': ('Compute SHA-256', 'Вычислить SHA-256'),
 'runtime_hashing': ('Hashing selected file…', 'Вычисление хеша выбранного файла…'),
 'runtime_copy_result': ('Copy result', 'Копировать результат'),
 'runtime_hash_complete': ('Hash operation complete', 'Вычисление хеша завершено'),
 'runtime_copy_failed': ('Copy failed', 'Ошибка копирования'),
 'runtime_raw_warning': ('Raw copy: no privacy masking. Review before sharing.',
                         'Необработанная копия: без маскирования данных. Проверьте перед отправкой.'),
 'runtime_masked_warning': ('Best-effort masking only. Review before sharing. Checks apply to declared assertions '
                            'before masking.',
                            'Маскирование без гарантии полноты. Проверьте перед отправкой. Проверки относятся к '
                            'заявленным assertions до маскирования.'),
 'runtime_warm_ready': ('AI result prepared locally. Click Copy to share; review before sending.',
                        'Результат для AI подготовлен локально. Нажмите «Копировать» и проверьте данные перед '
                        'отправкой.'),
 'runtime_active_operation': ('Finish the active operation first', 'Сначала завершите активную операцию'),
 'runtime_profiles': ('Workspace profiles', 'Профили рабочих папок'),
 'runtime_profile_existing': ('Select an existing workspace first', 'Сначала выберите существующую рабочую папку'),
 'runtime_profile_save': ('Save current workspace', 'Сохранить текущую рабочую папку'),
 'runtime_profile_name': ('Profile name', 'Имя профиля'),
 'runtime_profile_replace': ('Replace profile?', 'Заменить профиль?'),
 'runtime_profile_missing': ('Workspace no longer exists', 'Рабочая папка больше не существует'),
 'runtime_profile_save_current': ('Save current', 'Сохранить текущую'),
 'runtime_profile_use': ('Use selected', 'Использовать выбранный'),
 'runtime_profile_remove': ('Remove profile', 'Удалить профиль'),
 'runtime_task_loaded': ('AI task loaded: {task} — review before running',
                         'Задача AI загружена: {task} — проверьте перед запуском'),
 'runtime_copy_prepare': ('Preparing {mode}…', 'Подготовка копии ({mode})…'),
 'runtime_copied': ('Copied {mode} — {name}', 'Скопировано ({mode}) — {name}'),
 'runtime_checks': (' | Checks: {verdict}', ' | Проверки: {verdict}'),
 'runtime_masked': (' | Masked: {count}', ' | Маскирований: {count}'),
 'runtime_cancelled': ('CANCELLED', 'ОТМЕНЕНО'),
 'runtime_exit_zero': ('EXIT 0', 'КОД ВЫХОДА 0'),
 'runtime_exit_failed': ('FAILED / EXIT {code}', 'ОШИБКА / КОД ВЫХОДА {code}')}
for _key, (_english, _russian) in _RUNTIME_MESSAGES.items():
    _MESSAGES['en'][_key] = _english
    _MESSAGES['ru'][_key] = _russian


_HISTORY_MESSAGES = {'history_search': ('Search tasks, IDs or workspaces…', 'Поиск задач, ID или рабочих папок…'), 'history_task': ('Task', 'Задача'), 'history_time': ('Time', 'Время'), 'history_duration': ('Duration', 'Длительность'), 'history_all_runs': ('All runs', 'Все запуски'), 'history_exit_zero': ('Exit code 0', 'Код выхода 0'), 'history_exit': ('Exit code {code}', 'Код выхода {code}'), 'history_cancelled': ('Cancelled', 'Отменено'), 'history_partial': ('Incomplete', 'Не завершён'), 'history_unknown': ('Unknown', 'Неизвестно'), 'history_no_selection': ('Select a run to see its details.', 'Выберите запуск, чтобы увидеть подробности.'), 'history_selected': ('{count} reports selected', 'Выбрано отчётов: {count}'), 'history_visible': ('{shown} of {total} runs', 'Запусков: {shown} из {total}'), 'history_empty': ('No matching runs.', 'Нет подходящих запусков.'), 'history_details': ('Run details', 'Сведения о запуске'), 'history_detail': ('Process: {status}   •   Duration: {duration}\nStarted: {date}   •   Task ID: {task}\nWorkspace: {workspace}\nReport: {report}', 'Процесс: {status}   •   Длительность: {duration}\nНачало: {date}   •   ID задачи: {task}\nРабочая папка: {workspace}\nОтчёт: {report}'), 'history_assert_loading': ('Checking declared assertions…', 'Проверка заявленных условий…'), 'history_assert_status': ('Assertions: {status} ({passed}/{total})', 'Проверки: {status} ({passed}/{total})'), 'history_assert_none': ('Assertions: not requested', 'Проверки: не заданы'), 'history_assert_limited': ('Assertions: report exceeds preview limit; open the report.', 'Проверки: отчёт превышает лимит предпросмотра; откройте отчёт.'), 'history_assert_unavailable': ('Assertions: unavailable', 'Проверки: недоступны'), 'history_assert_note': ('Exit code 0 is not a test verdict.', 'Код выхода 0 не означает успешного прохождения тестов.'), 'history_open': ('Open report', 'Открыть отчёт'), 'history_copy': ('Copy AI result', 'Копировать AI-результат'), 'history_more': ('More actions', 'Другие действия'), 'history_compare': ('Compare reports', 'Сравнить отчёты'), 'history_stats': ('Run statistics', 'Статистика запуска'), 'history_compare_stats': ('Compare statistics', 'Сравнить статистику'), 'history_export': ('Export reports', 'Экспорт отчётов'), 'history_session': ('Session details', 'Сведения о сессии'), 'history_folder': ('Open reports folder', 'Открыть папку отчётов'), 'history_raw_title': ('Copy unmasked report?', 'Копировать отчёт без маскирования?'), 'history_raw_question': ('The full report may contain private data. Copy it without masking?', 'Полный отчёт может содержать приватные данные. Копировать без маскирования?'), 'history_select_two': ('Select two runs to compare (Ctrl or Shift).', 'Выберите два запуска для сравнения (Ctrl или Shift).')}
_HISTORY_MESSAGES.update({
    'history_show_more': ('Show more runs', 'Показать ещё запуски'),
    'history_page_count': ('Showing {shown} of {matched} matching runs · {total} loaded', 'Показано {shown} из {matched} подходящих запусков · загружено {total}'),
})
for _key, (_english, _russian) in _HISTORY_MESSAGES.items():
    _MESSAGES['en'][_key] = _english
    _MESSAGES['ru'][_key] = _russian


_AI_RULE_MESSAGES = {
    'copy_ai_rules': ('Copy AI rules', 'Копировать правила для ИИ'),
    'ai_rules_copied': ('AI rules copied. Paste them into a new AI chat.', 'Правила для ИИ скопированы. Вставьте их в новый чат.'),
    'ai_rules_unavailable': ('AI rules are unavailable. Restore the distributed AI Operating Guide.', 'Правила для ИИ недоступны. Восстановите руководство AI Operating Guide из поставки.'),
}
for _key, (_english, _russian) in _AI_RULE_MESSAGES.items():
    _MESSAGES['en'][_key] = _english
    _MESSAGES['ru'][_key] = _russian


def ai_rules_text(root: Path) -> str:
    """Read only the static, bounded rules excerpt from the distributed guide."""
    path = root / 'docs' / 'COMMAND_RELAY_AI_GUIDE.md'
    with path.open('rb') as source:
        raw = source.read(256_001)
    if len(raw) > 256_000:
        raise ValueError('AI guide exceeds size limit')
    text = raw.decode('utf-8').replace('\r\n', '\n')
    start, end = '<!-- relay-ai-rules:start -->', '<!-- relay-ai-rules:end -->'
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError('Missing or ambiguous AI rules excerpt')
    _, _, remainder = text.partition(start)
    rules, marker, _ = remainder.partition(end)
    rules = rules.strip()
    if not marker or not rules.startswith('# Command Relay — AI working rules\n') or len(rules) > 12_000:
        raise ValueError('Invalid AI rules excerpt')
    return rules


def tr(key, language=DEFAULT_LANGUAGE):
    """Stable message IDs; missing translations fall back to English, not raw IDs."""
    default = _MESSAGES[DEFAULT_LANGUAGE][key]
    catalog = _MESSAGES.get(language, {}) if isinstance(language, str) else {}
    return catalog.get(key, default)


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
        'Choose language / Выберите язык\nSome tools and confirmations remain in English. / Некоторые инструменты и подтверждения пока на английском.',
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
