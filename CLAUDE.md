# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

零售通知自动分发工具 (Retail Notification Auto-Distribution Tool) — a Windows desktop PyQt5 app that distributes notification messages to WeCom (企业微信 / WeChat Work) targets. It has two independent delivery mechanisms in one tabbed UI:

1. **Group sending** (群组发送): posts Markdown to WeCom robot **webhook** URLs over HTTP.
2. **Personal sending** (个人发送): automates the WeCom PC client via `pyautogui` (search contact → OCR-verify department → click → paste message → Enter), and can attach files via the Windows clipboard `CF_HDROP` format.

All UI text, comments, and log messages are in Chinese. Target platform is Windows only (relies on `pywin32`, `pyautogui`, PaddleOCR).

## Critical Environment Constraints

- **Python 3.10 is required.** `paddlepaddle==2.6.2` (pinned in `requirements.txt`) is incompatible with other versions. The included `venv/` is Python 3.10.11.
- **The project path must not contain non-ASCII (Chinese) characters**, or the Qt app fails to start (per `README.txt`). The current path is fine.
- The app automates the user's mouse/keyboard during personal sending — it is inherently interactive and cannot be fully tested headless. WSL2/Linux cannot run the GUI or PaddleOCR flows; development happens on Windows.

## Commands

```bash
# Activate the bundled virtualenv (Windows)
venv\Scripts\activate.bat

# Install dependencies (mirror used by build.bat)
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn

# Run the app
python main.py

# Package with PyInstaller (produces dist\零售通知工具\零售通知工具.exe)
build.bat
# or: pyinstaller "零售通知工具.spec"
```

## Architecture

### Entry point
`main.py` sets `BASE_DIR` (handles frozen/PyInstaller vs. dev layout), configures logging to `logs/app.log`, then boots the PyQt5 `QApplication` and `MainWindow`.

### `core/` — business logic (no UI)
- `config.py` — three JSON-backed config managers, each persisting to `data/`:
  - `GroupConfig` → `groups.json`: `[{id, name, webhook, category, enabled}]`. Also CSV/Excel import/export.
  - `TemplateConfig` → `templates.json`: `[{id, name, content}]` Markdown message templates containing `{placeholder}` variables (e.g. `{topic}`, `{time}`). Seeds 3 defaults if the file is missing.
  - `PersonConfig` → `persons.json`: `[{id, name, unit, tag, enabled}]`. `tag` is a comma-separated list used for filtering. CSV/Excel import/export, `clear_all()`.
  - All follow the same pattern: `load()` on init (empty list on parse error), `save()` writes UTF-8 JSON with `ensure_ascii=False`.
- `sender.py` — `WebhookSender` (HTTP POST of Markdown to `qyapi.weixin.qq.com/cgi-bin/webhook/send` with `interval`/`retries`/`timeout`; honors a `_stop_flag`), `SendResult` (shared result type across both senders), `SendLog` (per-run log + `logs/history.json`).
- `personal_sender.py` — `PersonalSender` (pyautogui automation; mirrors `WebhookSender`'s callback/stop interface). Flow: activate WeCom window → `Ctrl+Alt+F` search → paste name → `get_ocr().find_contact(name, unit)` → click result → `_paste_and_send` (text first, then files). `dry_run=True` verifies search without sending. `pyautogui.FAILSAFE` is enabled — moving the mouse to the screen top-left corner is the emergency stop.
- `ocr_helper.py` — `WeComOCR` wraps PaddleOCR (lazily initialized; `get_ocr()` is the module-level singleton). `find_contact()` scans OCR blocks for the target name with the unit in the adjacent block; falls back to clicking "查看全部" and arrow-key scrolling if not found. `capture_result_area()` locates the "全局搜索" window via `pygetwindow`. Hardcoded capture coordinates are tuned for specific screen resolutions.
- `clipboard_helper.py` — `copy_files_to_clipboard()` writes a `DROPFILES`/`CF_HDROP` structure (UTF-16LE) so `Ctrl+V` pastes files as attachments in WeCom. Requires `pywin32`.

### `ui/` — PyQt5 panels
`MainWindow` (`ui/main_window.py`) hosts a `QTabWidget` with four tabs, wired to the config managers:
- `msg_editor.py` — `MsgEditorPanel`: template picker, message editor with `{variable}` insertion, live Markdown-ish preview.
- `group_panel.py` — `GroupPanel`: group CRUD, search/filter, CSV/Excel import/export. Validates webhook URLs against the `https://qyapi.weixin.qq.com/cgi-bin/webhook/send` prefix.
- `send_panel.py` — `SendPanel`: group webhook sending. Interval (WeCom rate limit: **20 msgs/min/robot**, default 3s), retries, target-group checkboxes, progress bar, log, history. `SendThread` (QThread subclass) runs `WebhookSender` off the UI thread; `VariableDialog` prompts for `{placeholder}` substitution before sending.
- `personal_panel.py` — `PersonalPanel`: person table with enable checkboxes, unit/tag multi-select filters (`MultiCheckFilterButton`), name search, file attachment list, send params. `PersonalSendWorker` (a `QObject` moved onto a `QThread`) runs `PersonalSender`.

### Concurrency convention
Sending always runs in a background `QThread` to keep the UI responsive; progress/result/finish are delivered via `pyqtSignal`, and stopping is cooperative via the sender's `_stop_flag`. Note the two styles in use: `send_panel.py` subclasses `QThread` (`SendThread`), while `personal_panel.py` uses the recommended moveToThread pattern (`PersonalSendWorker`). Prefer the moveToThread pattern for new code.

## Data & Runtime Files

- `data/` — JSON state (`groups.json`, `templates.json`, `persons.json`); the app creates them at runtime. `groups.json` and `templates.json` are gitignored — only `sample_groups.csv` / `sample_person.xlsx` / `templates.json` are committed. `build.bat` copies `data/` into the PyInstaller output.
- `logs/` — `app.log` (app-level logging set up in `main.py`), `send.log` (sender logging set up in `sender.py`), `history.json` (send history). All gitignored.
- `零售通知工具.spec` — PyInstaller spec with `collect_all` for Paddle/PyQt stack, whole-package dir copies of native `.pyd`/`.dll` packages, and excludes (`torch`, `tensorflow`, `paddle.distributed`, …) to slim the bundle. Touch this only if the dependency set changes.

## Gotchas

- `requirements.txt` pins exact versions (`numpy==1.26.4`, `paddlepaddle==2.6.2`, `PyQt5==5.15.11`) — changing them can silently break OCR or the build.
- `SendPanel.get_message_content()` locates the message editor by walking up the Qt parent chain for an object with a `msg_editor` attribute — keep that attribute name when refactoring.
- Personal sending flows require the WeCom PC client open and logged in; `PersonalSender.check_dependencies()` guards the pyautogui/pyperclip install.
- `ocr_helper.py` contains a lot of commented-out legacy code and debug prints — treat it as exploratory. The `find_contact` / `_scan_and_match` / `_scroll_and_match` path is the active one.
