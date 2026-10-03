<div align="center">

<img src="./assets/logo.png" alt="tchMaterial-parser Logo" width="128" />

# tchMaterial-parser (Enhanced Fork)

**A downloader for the [electronic textbooks](https://basic.smartedu.cn/tchMaterial/) on China's [National Smart Education Platform](https://basic.smartedu.cn/)**

**[English](README_EN.md) · [简体中文](README.md)**

Built on top of [the original project](https://github.com/happycola233/tchMaterial-parser), it is far more tolerant of rate limiting and dead resources when downloading in bulk.

<sub>Based on the original project's **v4.3** source. Downloading, parsing and PDF bookmarks work exactly as before.</sub>

[![Python Version](https://img.shields.io/badge/Python-3.10+-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square)](#-download--install)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)

[🆕 What changed](#-what-this-fork-changes) · [📥 Install](#-download--install) · [🛠️ Usage](#️-usage) · [❓ FAQ](#-faq)

</div>

---

> [!CAUTION]
> **⚠️ Every line of code in this fork was written by AI.**
> **For your own safety, please don't read it yourself** — hand it to an AI instead.
> If you insist on reading it anyway, you accept the risk of dizziness, chest tightness, and the occasional “what on earth is this?”. 😄

---

## 📌 About this fork

This is a **personal fork** of [happycola233/tchMaterial-parser](https://github.com/happycola233/tchMaterial-parser), based on the original **v4.3** source, aimed at the “download a few hundred textbooks in one go and keep hitting the platform's rate limit” use case.

The original has one painful flaw when downloading in bulk: once the platform starts rate limiting you, or one resource happens to be unavailable, the app fails file after file, floods you with errors, and keeps retrying the same file that will never succeed — hammering the rate limit even harder.

This fork enhances that one area only. **Existing features and the UI layout are unchanged.**

## 🆕 What this fork changes

| Change | Description |
| :-- | :-- |
| 🛡️ **Rate-limit circuit breaker** | When several *different* files fail within a short window, the app treats it as rate limiting and pauses (3 minutes by default; the cooldown doubles on repeated trips, capped at 30 minutes), then resumes automatically. A single broken file failing over and over will **not** trip it. |
| 🔍 **Automatic failure triage (burst detection)** | When a file fails, the app skips it and keeps downloading the others. At the end of the batch it looks at *when* those failures happened: several different files failing within a short window (a burst) means rate limiting, so it waits out the cooldown and retries those files once. An isolated failure — nothing else failing around it — means that particular resource is unavailable, so it is reported and never retried. **Any single file is attempted at most twice per batch**, so nothing is retried forever. |
| ⏸️ **Pause / Resume** | Pausing lets in-flight files finish, then stops starting new ones. Progress is kept, and “Resume” picks up where it left off. |
| ⛔ **Cancel all** | Aborts the batch: queued files are dropped, in-flight transfers are interrupted at a chunk boundary and their temp files cleaned up, and already-finished files are untouched. |
| 📋 **Download log** | The log panel in the bottom-right corner records every file's result, the failure reason (with a plain-language explanation of the HTTP status code), why the app decided it was rate limiting, and the cooldown countdown. |
| ⚙️ **Download settings** | Seven parameters you can tune and save locally: concurrency, minimum request interval, rate-limit threshold, cooldown length, retry count for rate-limited files, 400-retry count, and download timeout. |

> [!NOTE]
> This fork ships a **Windows x64** prebuilt executable (see [Releases](https://github.com/asdflkj666/tchMaterial-parser/releases)). **Linux, macOS and Windows Arm64 must run from source.** The installers published by the original project **do not include** any of the improvements above.

## ✨ Features

### Added by this fork

- 🛡️ **Automatic rate-limit protection** — waits out throttling automatically instead of flooding you with errors.
- 🔍 **Automatic failure triage** — tells “this file is dead” apart from “you are being throttled”, and handles each differently.
- 📋 **Download log** — failure reasons, triage decisions and cooldown countdown in one place.
- ⏸️ **Pause & cancel** — full control over a running batch.
- ⚙️ **Download settings** — concurrency, intervals and thresholds exposed in the UI, so you can tune them for your network.

### Inherited from the original

- 📚 **Bulk download** — paste multiple textbook preview URLs and download them in one go.
- 📂 **Automatic naming** — files are named after the textbook and sorted into folders by stage / subject / edition.
- 🔖 **Automatic PDF bookmarks** — with “添加 PDF 书签” enabled, bookmarks are added after download so you can jump between chapters.
- 🔑 **Access Token support** — paste a token [manually](#2--set-an-access-token-optional) and it is saved for next time.
- 🔎 **Resource search** — search by name or by combinations such as stage / subject / grade.
- 🖥️ **High-DPI support** — the UI is tuned for high-resolution displays.
- 🌗 **Dark mode** — follows the system theme, or switch manually and it is remembered.
- 💻 **Cross-platform** — Windows, Linux and macOS (a graphical desktop is required).

## 📥 Download & install

### 🪟 Windows: grab the executable

Download the latest Windows executable from [Releases](https://github.com/asdflkj666/tchMaterial-parser/releases) — named like `tchMaterial-parser-v4.3-fork.2.exe` — and double-click it: **a single file, nothing to install, no Python needed**.

> [!NOTE]
> - The binary is built locally by the maintainer with PyInstaller and is **not code-signed**. On first launch, Windows SmartScreen may warn about an “unknown publisher” — click “More info” → “Run anyway”.
> - **Windows x64 is the only platform with a prebuilt binary.** For Linux, macOS or Windows Arm64, run from source as described below.

### 🐍 Other platforms: run from source

Python 3.10+ with Tkinter is required:

```sh
# from the source directory — installs sv-ttk, requests, pypdf, etc.
python -m pip install .

# run
python ./src/main.py
```

> [!NOTE]
> - The UI is built with **Tkinter**. Official Windows and macOS Python builds ship with it; some Linux distributions need it installed separately, e.g. `sudo apt install python3-tk` on Debian/Ubuntu.
> - Minimal Linux installations may lack Chinese and emoji fonts, which shows up as empty boxes in the UI. Install them if needed, e.g. `sudo apt install fonts-noto-cjk fonts-noto-color-emoji`.
> - The interface itself is **in Chinese**. Button names quoted throughout this document are the literal labels you will see in the app.

### Need a Linux / macOS binary? Use the original project

The original project ships binaries for **Windows / Linux / macOS** (x86_64 and Arm64), plus WinGet and AUR packages:

| Channel | Where to get it |
| :-- | :-- |
| 🐙 GitHub Releases | [happycola233/tchMaterial-parser/releases](https://github.com/happycola233/tchMaterial-parser/releases) |
| 📦 WinGet (Windows) | `winget install happycola233.tchMaterial-parser` |
| 🐧 AUR (Arch Linux) | `yay -S tchmaterial-parser` |

> [!WARNING]
> Those packages are published by the **original project** and **do not include this fork's improvements** (rate-limit protection, pause/cancel, the download log, download settings). To get those, use this fork's Windows build or run it from source as shown above.

## 🛠️ Usage

### 1. ⌨️ Paste textbook links

Paste the **preview page URL** of a textbook into the text box. Multiple URLs are supported, one per line.

**Example URL**:

```text
https://basic.smartedu.cn/tchMaterial/detail?contentType=assets_document&contentId=XXXXXX&catalogType=tchMaterial&subCatalog=tchMaterial
```

### 2. 🔑 Set an Access Token (optional)

> [!TIP]
> This step is **optional**. Without a token the app falls back to other methods, but those **do not work long-term**, so setting a token is still recommended.

> [!WARNING]
> A few tips:
>
> 1. **Log in first, then paste the code!**
> 2. Paste into the console prompt itself — not into a filter box.
> 3. If the browser warns you about pasting, type “allow pasting” first, then paste again.
>
> ![Hint](./docs/images/get_token.png)

1. **Open your browser** and log in to the [National Smart Education Platform](https://auth.smartedu.cn/uias/login).
2. Press **F12** or **Ctrl+Shift+I** (or right-click → Inspect) to open DevTools, then switch to the **Console** tab.
3. Paste the following snippet into the console and press Enter:

   ```js
   (function () {
     const authKey = Object.keys(localStorage).find(
       key => /^ND_UC_AUTH-[^&]+&[^&]+&token$/.test(key),
     );
     if (!authKey) {
       console.error("未找到登录凭据，请确保已登录！");
       return;
     }
     const tokenData = JSON.parse(localStorage.getItem(authKey));
     const { access_token, mac_key, diff } = JSON.parse(tokenData.value);
     const credentials = JSON.stringify({ access_token, mac_key, diff });
     console.log(
       "%cCopy the whole JSON below and paste it into the downloader:",
       "color: green; font-weight: bold",
     );
     console.log(credentials);
   })();
   ```

4. Copy the **whole JSON** the console prints, then click “**设置 Token**” in the app, paste it and save.

> [!NOTE]
> The Access Token expires. If downloads start failing, obtain and set a new one.
>
> Note that `localStorage` also contains `ND_UC_AUTH-…&sdk_cache` (cached account info) which holds no token — run the snippet above instead of copying entries by hand from the Application panel.

### 3. 🚀 Start downloading

Click “**下载**” and the app will parse and download the textbooks automatically.

Bulk downloads are supported: every file is named after the textbook and saved into the directory you choose.

With “**添加 PDF 书签**” enabled, bookmarks are added to each textbook once its download finishes, so you can jump straight to a chapter when reading.

<div align="center">

![A PDF with bookmarks](./docs/images/bookmark.png)

</div>

### 4. 🛡️ Rate-limit protection, pause and the download log

When downloading many files, the platform may throttle your requests. This fork handles that automatically — nothing to configure:

- **A failing file is skipped, not retried in place** — the app moves straight on to the next file.
- **“File is dead” is told apart from “you are throttled”** — the app looks at *when* the failures happened, not at whether anything happened to succeed later. A burst of failures across several different files means rate limiting: it pauses (longer each time it happens, up to 30 minutes), resumes after the cooldown and retries those files once. An isolated failure — nothing else failing around it — means that resource is unavailable on the platform's side and is reported as such.
- **Pause and cancel at any time** — “暂停” lets in-flight files finish, then stops starting new ones (progress is kept); “继续” resumes. “取消” aborts the whole batch: in-flight transfers are interrupted and their temp files removed, while finished files are kept.
- **Download log** — the “下载日志” panel in the bottom-right corner records each file's outcome, the failure reason (including a plain-language explanation of the HTTP status code), the triage decision, and the cooldown countdown. When the batch ends, the **full failure list (with relative paths) is written into the log too**.
- **The failure list is saved as a file** — the summary dialog only reports counts (a few hundred failures times their long reasons would overflow the screen), while the full list is saved as `下载失败清单.txt` in the download directory and you are asked whether to open it. You can also open that file later. It is what you use to rerun just the failed files.

If the defaults do not suit your network, click “**下载设置**” to adjust concurrency, request interval, the rate-limit threshold, cooldown length, retry count and more. Changes are saved locally and take effect immediately.

## ❓ FAQ

<details open>
<summary><b>1. ⚠️ Why did a download fail?</b></summary>

<br />

- If you have not set an Access Token, the fallback method may have stopped working — [set an Access Token](#2--set-an-access-token-optional) 🔑.
- If you have set one, it is time-limited (usually 7 days), so it has most likely **expired** — get a new one.
- **Check your network** 🌐; an unstable connection can cause failures.
- **Make sure the URL is valid** 🔗; some older resources have been removed.
- Check the “**下载日志**” panel in the bottom-right corner: the failure reason there (with a plain-language status-code explanation) will tell you which kind of problem it is.

</details>

<details>
<summary><b>2. 📋 What do the log messages mean?</b></summary>

<br />

- **“文件自身不可用，已跳过重试”** — this was an isolated failure (nothing else failing around it), so the platform was up and this particular resource is simply unavailable (e.g. delisted). The app will not waste time retrying it.
- **“疑似限流，重试后仍失败”** — several files were failing close together, so it was judged to be rate limiting; the app paused and retried once, without success.
- **“[清单] …”** — the complete failure list produced at the end of the batch, split into the two categories above with relative paths and reasons. The same content is saved as `下载失败清单.txt` in the download directory, so you can rerun just those files.
- **“[限流] … 暂停 X 分 Y 秒后自动继续”** — several different files failed in a short window, so the app paused to back off; it resumes automatically when the countdown ends.
- **HTTP status codes**: `400` bad request (usually throttling or a dead URL), `401` not logged in / token expired, `403` no permission, `404` resource not found, `429` too many requests (throttling), `5xx` platform-side server problem.

</details>

<details>
<summary><b>3. 💾 Where is the Access Token stored?</b></summary>

<br />

- **Windows**: in the registry, under `HKEY_CURRENT_USER\Software\tchMaterial-parser`, value `AccessToken`.
- **Linux**: in `~/.config/tchMaterial-parser/data.json`.
- **macOS**: in `~/Library/Application Support/tchMaterial-parser/data.json`.
- **Other platforms**: not persisted at present.

> Download settings (concurrency, intervals, thresholds…) are stored in the same place.

</details>

<details>
<summary><b>4. 🔐 Can the token leak?</b></summary>

<br />

- The app **never uploads** your token and never stores it in the cloud; it is only used to authorise local requests.
- **Do not share your token publicly** — anyone who has it can use your account.

</details>

## 🤝 Feedback & upstream

This fork is maintained for personal use, but **issues and pull requests are welcome**. If you hit a problem in an original feature (parsing, downloading, bookmarks…), you can also report it to [the original project](https://github.com/happycola233/tchMaterial-parser/issues). If you want to make changes yourself, just fork the source; see the download/rate-limit conventions in `AGENTS.md`.

The original project is developed and maintained by [@happycola233](https://github.com/happycola233) and many contributors — almost all of this fork's code comes from them. Thanks also to [@PtJade-Ceramic](https://github.com/PtJade-Ceramic) (WinGet suggestion) and [@iamzhz](https://github.com/iamzhz) (AUR package).

## ⚖️ Disclaimer

- This tool only makes downloading **more convenient**. It does not host, store or redistribute any content; all resources come directly from the [National Smart Education Platform](https://basic.smartedu.cn/).
- Copyright of the downloaded resources belongs to the platform and the respective rights holders. Use them for personal study and teaching reference only — **do not use them commercially or redistribute them**.
- Follow the platform's terms of service and your local laws when using this tool. Any consequences of use are borne by the user.
- This project has **no affiliation with or endorsement from** the National Smart Education Platform.

## 📜 License

Like the original project, this fork is released under the [MIT License](LICENSE). Copyright belongs to the original author and contributors. Free to use and build upon.

It uses some image assets from [Microsoft Fluent Emoji](https://github.com/microsoft/fluentui-emoji), licensed under the [MIT License](./licenses/Microsoft-Fluent-Emoji.txt).

## 💌 Links

- 📚 Archived textbook PDFs are also available in [ChinaTextbook](https://github.com/TapXWorld/ChinaTextbook).
