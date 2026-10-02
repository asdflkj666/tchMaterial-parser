<div align="center">

<img src="./assets/logo.png" alt="tchMaterial-parser Logo" width="128" />

# tchMaterial-parser（增强分支）

**[简体中文](README.md) · [English](README_EN.md)**

**[国家中小学智慧教育平台](https://basic.smartedu.cn/) [电子课本](https://basic.smartedu.cn/tchMaterial/)下载工具**

在[原版](https://github.com/happycola233/tchMaterial-parser)基础上，增强了批量下载遇到限流与坏资源时的容错能力。

<sub>基于原项目 **v4.3** 源码修改，原版的下载、解析、书签等功能完整保留。</sub>

[![Python Version](https://img.shields.io/badge/Python-3.10+-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square)](#-下载与安装方法)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)

[🆕 改了什么](#-相对原版的改动) · [📥 安装](#-下载与安装方法) · [🛠️ 使用方法](#️-使用方法) · [❓ 常见问题](#-常见问题)

</div>

---

> [!CAUTION]
> **⚠️ 本分支的代码全部由 AI 生成。**
> **为了你的生命安全，请不要自己阅读这些代码**——需要看代码时，请交给 AI 看。
> 若你坚持人工阅读，请自行承担头晕、胸闷，以及「这写的什么玩意儿」的风险。😄

---

## 📌 关于本分支

这是 [happycola233/tchMaterial-parser](https://github.com/happycola233/tchMaterial-parser) 的**个人增强分支**，源码取自原项目 **v4.3**，用于「一次下载几百本、经常撞上平台限流」的场景。

原版在批量下载时有个难受的地方：一旦被平台限流或因某个资源不可用而失败，程序会一个个失败过去，刷出一整屏错误，还会反复重试同一个根本下不动的文件，把限流打得更死。

本分支只针对这一环做增强，**不改动原有功能与界面结构**。

## 🆕 相对原版的改动

| 改动 | 说明 |
| :-- | :-- |
| 🛡️ **限流熔断** | 短时间内有多个「不同文件」下载失败时判定为限流，自动暂停一段时间（默认 3 分钟，连续触发逐次翻倍、封顶 30 分钟），冷却结束后自动继续。单个文件反复失败不会误触发。 |
| 🔍 **失败自动定性（探针）** | 某个文件失败时，先跳过它继续下载其他文件：若其他文件仍能正常下载，说明是该文件自身不可用，直接列入失败清单、不再重试；若其他文件也失败，才判定为限流，冷却后重试一次。**任何文件单次任务内最多下载 2 次**，杜绝「一直重试一直下不了」。 |
| ⏸️ **暂停 / 继续** | 暂停时，正在下载的文件会先下载完成，之后不再开始新任务；已下载进度保留，点“继续”即可恢复。 |
| ⛔ **取消全部** | 中断整批任务：未开始的不再启动，正在传输的在分块处中断并清理临时文件，已下载完成的文件不受影响。 |
| 📋 **下载日志** | 界面右下角实时记录每个文件的结果、失败原因（含 HTTP 状态码的中文解释）、限流判定依据与冷却倒计时。 |
| ⚙️ **下载设置** | 并发下载数、请求最小间隔、限流触发阈值、冷却时长、疑似限流文件重试次数、400 重试次数、下载超时共 7 项参数，可在界面调整并保存到本机。 |

> [!NOTE]
> 本分支目前**只以源码方式提供**，没有预编译安装包。原项目发布的安装包**不含**上述增强功能。

## ✨ 工具特点

### 本分支新增

- 🛡️ **限流自动保护**：见上表，遇到限流自动等待、冷却后继续，不再刷屏报错。
- 🔍 **失败原因自动判定**：自动区分「这个文件下不动」和「被平台限流了」，处理方式不同。
- 📋 **下载日志**：失败原因、判定依据、冷却倒计时一目了然。
- ⏸️ **可暂停与取消**：批量任务随时可控。
- ⚙️ **下载技术设置**：把并发、间隔、阈值等参数暴露到界面，可按自己的网络情况调整。

### 原版已有

- 📚 **支持批量下载**：一次输入多个电子课本预览页面网址，即可批量下载电子课本文件。
- 📂 **自动命名文件**：自动使用电子课本的名称作为默认文件名，并按“学段／学科／版本”分类存放。
- 🔖 **自动添加书签**：开启 “添加 PDF 书签” 后，会在下载完成后为电子课本添加书签，查看 PDF 时可快速跳转。
- 🔑 **支持 Access Token**：支持[手动输入 Access Token](#2--设置-access-token可选) 并自动保存，下次启动自动加载。
- 🔎 **资源快速搜索**：可按资源名称或 “学段、学科、年级” 等分类组合搜索。
- 🖥️ **高 DPI 适配**：优化 UI 以适配高分辨率屏幕。
- 🌗 **深色模式**：跟随系统，也可手动切换并记住选择。
- 💻 **跨平台支持**：Windows、Linux、macOS（需要图形界面）。

## 📥 下载与安装方法

本分支没有预编译包，**唯一推荐方式是从源码运行**（需 Python 3.10+，且需带 Tkinter 的发行版）：

```sh
# 进入源码目录后安装依赖（会自动装好 sv-ttk、requests、pypdf 等）
python -m pip install .

# 启动
python ./src/main.py
```

> [!NOTE]
> - 本工具使用 **Tkinter** 构建图形界面。Windows 与 macOS 的官方 Python 通常已自带，而部分 Linux 发行版需要单独安装，例如在 Debian/Ubuntu 上执行 `sudo apt install python3-tk`。
> - 精简安装的 Linux 系统可能缺少中文字体与 Emoji 字体，界面上会出现方框，可按需安装，例如 `sudo apt install fonts-noto-cjk fonts-noto-color-emoji`。

### 想用安装包？请去原项目

原项目为 **Windows / Linux / macOS**（x86_64、Arm64）提供预编译程序，也支持 WinGet 与 AUR：

| 方式 | 获取途径 |
| :-- | :-- |
| 🐙 GitHub Releases | [happycola233/tchMaterial-parser/releases](https://github.com/happycola233/tchMaterial-parser/releases) |
| 📦 WinGet（Windows） | `winget install happycola233.tchMaterial-parser` |
| 🐧 AUR（Arch Linux） | `yay -S tchmaterial-parser` |

> [!WARNING]
> 上述安装包均由**原项目**发布，**不包含本分支的增强功能**。若你需要限流保护、暂停/取消、下载日志与下载设置，请按上面的方式从源码运行本分支。

## 🛠️ 使用方法

### 1. ⌨️ 输入电子课本链接

将电子课本的**预览页面网址**粘贴到工具文本框中，支持多个 URL（每行一个）。

**示例网址**：

```text
https://basic.smartedu.cn/tchMaterial/detail?contentType=assets_document&contentId=XXXXXX&catalogType=tchMaterial&subCatalog=tchMaterial
```

### 2. 🔑 设置 Access Token（可选）

> [!TIP]
> 此操作**不是必要的**，当未设置 Access Token 时工具会使用其他方法下载资源，但这一方法**并不长期有效**，因此仍然建议您执行这一步操作。

> [!WARNING]
> 友情提示：
>
> 1. **先登录账号，再粘贴代码！**
> 2. 粘贴代码时，不要粘贴到 “过滤” 或 “筛选器” 上，而是 “>” 后面！
> 3. 粘贴时如遇到警告，请先输入 “**允许粘贴**” 四个字，然后再次粘贴代码！
>
> ![提示](./docs/images/get_token.png)

1. **打开浏览器**，访问[国家中小学智慧教育平台](https://auth.smartedu.cn/uias/login)并**登录账号**。
2. 按下 **F12** 或 **Ctrl+Shift+I**，或右键——检查（审查元素）打开**开发者工具**，选择**控制台（Console）**。
3. 在控制台粘贴以下代码后回车（Enter）：

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
       "%c请复制下面整段 JSON 并粘贴到下载工具：",
       "color: green; font-weight: bold",
     );
     console.log(credentials);
   })();
   ```

4. 复制控制台输出的**整段 JSON**，然后在本工具中点击 “**设置 Token**” 按钮，粘贴并保存。

> [!NOTE]
> Access Token 可能会过期，若下载失败，请重新获取并设置新的 Token。
>
> 登录后的 `localStorage` 里还有 `ND_UC_AUTH-…&sdk_cache`（账号资料缓存），里面没有 Token。请运行上面的脚本，不要从开发者工具的 Application 面板里随便复制一项。

### 3. 🚀 开始下载

点击 “**下载**” 按钮，工具将自动解析并下载电子课本文件。

本工具支持**批量下载**，所有文件会自动按课本名称命名并保存在选定目录中。

若您开启了 “**设置 PDF 书签**”，则本工具会在课本下载完成后自动为其添加书签，在查看 PDF 时可快速跳转到指定位置。

<div align="center">

![添加了书签的 PDF 文件](./docs/images/bookmark.png)

</div>

### 4. 🛡️ 限流保护、暂停与下载日志

批量下载大量文件时，平台可能会限制请求速度。本分支内置了相应的保护机制，无需额外配置：

- **单个文件失败会自动放过**：某个文件下载失败时，工具会立即继续下载下一个文件，不会卡在原处反复重试。
- **自动区分「文件问题」与「限流」**：若失败后其他文件仍能正常下载，说明是该文件自身不可用，工具会直接把它列入失败清单；若其他文件也接连失败，则判定为被限流，自动暂停一段时间（连续触发会逐次延长，最长 30 分钟），冷却结束后继续下载，并对这些文件重试一次。
- **可随时暂停或取消**：点击 “暂停” 后，正在下载的文件会先下载完成，之后不再开始新任务（已下载的进度会被保留）；点击 “继续” 恢复。点击 “取消” 则中断整批任务（正在传输的文件会被中断并清理临时文件，已下载完成的文件不受影响）。
- **下载日志**：界面右下方的 “下载日志” 会实时记录每个文件的完成/失败情况、失败原因（含 HTTP 状态码的中文解释）、限流判定依据与冷却倒计时，方便您判断问题出在哪里。

若默认参数不适合您的网络环境，可点击 “**下载设置**” 调整并发下载数、请求间隔、限流判定阈值、冷却时长、失败重试次数等参数，修改会保存在本机并立即生效。

## ❓ 常见问题

<details open>
<summary><b>1. ⚠️ 为什么下载失败？</b></summary>

<br />

- 如果您没有设置 Access Token，可能是本工具使用的方法失效了，请[**设置 Access Token**](#2--设置-access-token可选)🔑。
- 如果您设置了 Access Token，由于其具有时效性（一般为 7 天），因此极有可能是 **Access Token 过期了**，请重新获取新的 Access Token。
- **确认网络连接是否正常**🌐，有时网络不稳定可能导致下载失败。
- **确保输入的网址有效**🔗，部分旧资源可能已被移除。
- 请查看界面右下方的 “**下载日志**”，其中的失败原因（含 HTTP 状态码的中文解释）会说明是哪种问题。

</details>

<details>
<summary><b>2. 📋 下载日志里的提示分别是什么意思？</b></summary>

<br />

- **“资源不可用，已跳过重试”**：该文件失败时，其他文件仍能正常下载，说明平台运行正常，是这份资源自身不可用（例如已被下架），工具不会再浪费时间重试。
- **“疑似限流，重试后仍失败”**：失败时其他文件也无法下载，判定为被平台限流；工具已暂停等待并重试过一次，仍未成功。
- **“[限流] … 暂停 X 分 Y 秒后自动继续”**：短时间内有多个不同文件下载失败，工具已自动暂停以避开限流，倒计时结束后会继续下载。
- **HTTP 状态码含义**：`400` 请求无效（多为限流或地址失效）、`401` 未登录或登录已过期、`403` 无权限访问、`404` 资源不存在、`429` 请求过于频繁（限流）、`5xx` 平台服务器暂时异常。

</details>

<details>
<summary><b>3. 💾 Access Token 保存在哪里？</b></summary>

<br />

- **Windows**：Token 会存储在**注册表** `HKEY_CURRENT_USER\Software\tchMaterial-parser` 项中的 `AccessToken` 值。
- **Linux**：Token 会存储在**文件** `~/.config/tchMaterial-parser/data.json` 中。
- **macOS**：Token 会存储在**文件** `~/Library/Application Support/tchMaterial-parser/data.json` 中。
- **其他操作系统**：目前暂不支持持久化。

> 下载设置（并发、间隔、阈值等）与 Token 保存在同一位置。

</details>

<details>
<summary><b>4. 🔐 Token 会不会泄露？</b></summary>

<br />

- 本工具**不会上传** Token，也不会存储在云端，仅用于本地请求授权。
- **请勿在公开场合分享 Token**，以免您的账号被他人使用，造成严重后果。

</details>

## 🤝 反馈与上游

本分支为个人自用而改，**不接受 Issue 与 Pull Request**。若您遇到的是解析、下载、书签等原版功能的问题，请到[原项目](https://github.com/happycola233/tchMaterial-parser/issues)反馈；若您也想改，直接 fork 源码即可，欢迎参考 `AGENTS.md` 中的下载与限流约定。

原项目由 [@happycola233](https://github.com/happycola233) 及众多贡献者开发维护，本分支的绝大部分代码来自他们。也感谢 [@PtJade-Ceramic](https://github.com/PtJade-Ceramic)（WinGet 分发建议）与 [@iamzhz](https://github.com/iamzhz)（AUR 发行包）。

## ⚖️ 免责声明

- 本工具**仅提供下载上的便利**，不存储、不托管、不分发任何资源内容，所有资源均直接来自[国家中小学智慧教育平台](https://basic.smartedu.cn/)。
- 所下载资源的**版权归原平台及相关权利人所有**，请仅用于个人学习与教学参考，**请勿用于商业用途或二次分发**。
- 使用本工具时请遵守该平台的服务条款及您所在地区的法律法规。因使用本工具产生的任何后果由使用者自行承担。
- 本项目与国家中小学智慧教育平台**没有任何隶属或合作关系**。

## 📜 许可证

本分支与原项目一样基于 [MIT 许可证](LICENSE)，版权归原项目作者及贡献者所有，欢迎自由使用和二次开发。

本项目使用了 [Microsoft Fluent Emoji](https://github.com/microsoft/fluentui-emoji) 中的部分图片资源，按照 [MIT 许可证](./licenses/Microsoft-Fluent-Emoji.txt)授权使用。

## 💌 友情链接

- 📚 您也可以在 [ChinaTextbook](https://github.com/TapXWorld/ChinaTextbook) 项目中下载归档的电子课本 PDF。
