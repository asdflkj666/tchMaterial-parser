# Agent 指南

这是一个面向[国家中小学智慧教育平台](https://basic.smartedu.cn/)的桌面工具，用来解析并批量下载电子课本等资源。

> [!IMPORTANT]
> 本仓库是 [happycola233/tchMaterial-parser](https://github.com/happycola233/tchMaterial-parser) 的个人 fork，代码**主要由 AI 生成与维护**。
> 阅读与修改时请以**实际行为、测试与运行结果**为准，不要依赖「看起来应该如此」的推断；不确定的地方先读代码或跑测试验证。

编写代码时请参考[**贡献者指南**](./CONTRIBUTING.md)，遵守其中的代码格式、文案等约定。

**深度思考，积极搜索互联网，查阅最新开发文档与行业最佳实践。**

若需要任何工具或依赖，请自行安装。

## 编写规则

1. 本工具支持的最低 Python 版本为 **3.10**，编写代码时请确保其能在 Python 3.10 中正常运行，例如在 f-string 嵌套字符串时应注意**引号问题**，使用类似于下述格式：

   ```python
   f"文本 {data['item']}"
   ```

   而不是：

   ```python
   f"文本 {data["item"]}"
   ```

2. 本工具在设计上支持 Windows、Linux、macOS 操作系统，编写代码时应确保**跨平台兼容性**。
3. 确保代码**可维护性**：
   - 实现新功能时应搜索已有实现，不要出现冗余代码；
   - 优先执行**最小修复**，避免回归，不要重构无关代码，不要为了修复一个小问题而引入一堆大改动；
   - 修复复杂问题时，应先**分析项目整体结构**再改动。
4. 修改代码后，应执行**测试与检查**。
5. 若用户要求修改工具的版本号，只需修改 `pyproject.toml` 与 `version_info.txt` 中的有关信息即可。

## 结构约定

1. 临时文件统一放在 `.tmp/` 目录（该目录已加入 `.gitignore`，不存在时自行创建）。
2. 除非用户提到，否则默认无需阅读 `.devfiles/` 下的文件，且禁止做任何修改。
3. 添加/修改大功能时，应同步添加/修改 `tests/` 目录下的测试文件。
4. 未被 `.gitignore` 忽略的文件**不得包含明文 Access Token 等敏感数据**。
5. 介绍文档有中文与英文两个版本：`README.md`（简体中文）与 `README_EN.md`（English），两者内容一一对应，**改其中一份时请同步另一份**。

## 下载与限流约定

批量下载需要容忍平台限流，相关逻辑集中在 `download_control.py` 与 `ui/download_panel.py`，改动时请保持以下约定：

1. **熔断按“不同 URL”去重**：`controller.report_failure(url)` 统计 60 秒内失败过的不同 URL 数量（阈值 `circuit_threshold`），同一文件反复失败只算一次，避免单个坏文件把整批拖进冷却。只有终态 400/429/网络异常才上报；401/403/404 不上报也不重试。
2. **失败先放过、末尾再裁决**：首轮失败不做原地重试，直接继续下一个文件；批次末尾用 `classify_failures()` 区分「文件自身不可用」与「疑似限流」。判据由 `burst_failure_keys()` 给出，做法是对 `state["failed_at"]` 做**成片检测**：失败按时刻排序，相邻间隔不超过 `config.CIRCUIT_FAILURE_WINDOW` 的归为一簇，成员数 ≥ 2 判为限流，孤立失败判为文件自身不可用。只对「疑似限流」的再试一次，重试过要标记 `state["retried"]` 并重新裁决。
   - **不要**把判据改成「失败之后到批次结束之间有没有别的文件成功」：大批量任务里这个条件恒为真（批次动辄跑几小时），会导致**所有**失败都被判成文件自身不可用、一个都不重试。实测一次 6 小时批次 213 个失败全部被跳过；其中抽查若干「资源不可用」的文件，几十分钟后同名同书的文件又下载成功了。
   - 失败时刻由 `download_file` 自己写进 `state["failed_at"]`（`time.monotonic()`），`classify_failures()` 保持**只读 states 的纯函数**，不要让它依赖 `controller` 的批次状态。
3. **失败清单要落盘，结束弹窗只报数字**：`log_failure_list()` 写进日志区、`write_failure_list()` 写成下载目录下的 `下载失败清单.txt`，便于用户照着重跑。**不要**把逐条失败原因塞回 `messagebox`——几十上百个失败乘以每条的长原因会把对话框撑满整个屏幕（实测一次 213 个失败）。弹窗只用 `askyesno` 报数量并询问是否打开清单文件，`open_path()` 负责跨平台打开。
4. **暂停按文件边界生效**：进行中的文件会下完，未开始的任务在 `controller.wait_to_start()` 处阻塞；取消则在分块写入点抛 `DownloadCancelled` 并清理 `.tmp`。
5. **下载设置**统一在 `config.DOWNLOAD_SETTING_SPECS` 中声明（含默认值、范围、说明），界面由 `ui/settings_window.py` 自动生成；`min_request_interval` 与 `http400_retries` 通过 `download_panel.apply_download_settings()` 同步到模块变量 `_MIN_REQUEST_INTERVAL` / `_400_RETRY_DELAYS`——这两个变量被测试直接 patch，**不要删除或内联**。
6. **配置与 UI 的解耦**：设置窗口只写 `config`，不直接依赖下载模块；保存成功后由 `config.on_download_settings_changed()` 通知，接线放在 `app.py`。新增需要「保存后立即生效」的配置项时沿用这条路径。
7. **界面控件句柄**统一放在 `download_panel.widgets`（`PanelWidgets` 容器）里，由 `app.py` 通过 `bind_widgets()` 注入；新增控件请在容器里加字段，不要再引入模块级全局变量。
8. **日志**统一走 `download_panel.log_message()`（可在任意线程调用，内部切回主线程），失败原因要带 HTTP 状态码的中文解释（`HTTP_STATUS_HINTS` / `status_hint()`）。

## 测试与检查

```sh
python -m pip install pytest flake8
python -m pytest tests/ -q
python -m flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
```

- 改动下载相关逻辑时，除单测外请特别关注 `tests/test_download_control.py`、`tests/test_download_batch.py`、`tests/test_download_progress.py`。
- 部分测试直接 patch 模块级参数（如 `download_panel._PROGRESS_REFRESH_INTERVAL`、`_MIN_REQUEST_INTERVAL`、`_400_RETRY_DELAYS`），**不要把这些变量内联或改名**。
- GUI 只能用真实桌面环境验收，不要在无图形界面的环境里硬跑。

## 构建与发布

- 打包使用 `tchMaterial-parser.spec`（PyInstaller）：Windows 依赖 `version_info.txt` 与 `assets/icon.ico`，macOS 依赖 `assets/logo.icns`。这几个是**真实文件**（索引里 100644），处理打包配置时不要把 `assets/` 下的软链接误当成它们。
- **正式发布 = 本地编译 + 网页手动上传产物，不使用 CI 自动构建。** 本地命令（**必须在仓库根目录执行**，spec 里用的是相对路径）：

  ```sh
  py -3 -m pip install pyinstaller
  py -3 -m PyInstaller tchMaterial-parser.spec --noconfirm
  ```

  产物名由 spec 从 `pyproject.toml` 现读版本号生成，形如 `dist/tchMaterial-parser-v4.3-fork.2.exe`（单文件、无控制台窗口）；`build/`、`dist/` 已被 `.gitignore` 忽略，不会污染 git 状态。
- `.github/workflows/build-release.yml` **只在手动 `workflow_dispatch` 时运行**（需填一个已存在的 tag）。**发布 Release 不会触发它，这是刻意如此**：不要把 `release: published` 加回去，否则每次发版都会连带触发全平台构建，而且产物会和手动上传的同名资产冲突（GitHub 拒绝重复资产名，会上传失败）。需要其它平台产物时，去 Actions 页手动跑一次；该矩阵覆盖 Windows / Linux / macOS 的 x64 与 Arm64。
- **版本号采用「原项目版本 + fork 后缀」**：以所基于的上游版本为基准，后缀是该分支的第几次发布，每次发新 Release 递增 `fork.N`。当前为 `4.3+fork.2`。tag 与产物文件名里把 `+` 写成 `-`，即 tag `v4.3-fork.2`、产物 `tchMaterial-parser-v4.3-fork.2.exe`。
- **`pyproject.toml` 里只能用 `+` 不能用 `-`**：`4.3+fork.1` 是合法的 PEP 440 本地版本段，而 `4.3-fork.1` / `4.3.fork.1` 都非法，`pip install .` 会直接报 `Invalid version`。文件名与 tag 不受 PEP 440 约束，用 `-` 更易读，转换由 spec 完成。
- **tag 命名要避开上游已用过的 tag**（上游已发布到 `v4.x`）；手动跑矩阵前必须先把 tag push 到远端，否则 `actions/checkout` 按 tag 检出会失败。
- 版本号只维护两处：`pyproject.toml` 的 `version`（程序界面显示、spec 产物命名都读这里）与 `version_info.txt`（Windows exe 属性，字符串字段用 `4.3+fork.2`、数字四元组固定用 `(4, 3, 0, 0)`）。`tchMaterial-parser.spec` 会现读 `pyproject.toml`，所以改版本号不必再改 spec。**改完需重新 `pip install .`**，否则界面标题仍显示旧版本。
- 产物为**未签名**构建，杀毒软件可能提示；发布说明中应写明这一点，并说明本仓库的增强功能**不包含**在上游发布的安装包中。

## Git 操作

1. 除非用户要求，否则不要执行 commit 与 push。
2. 若被用户要求写 commit：
   - 请只生成遵循「**Conventional Commit**」的提交消息，内容应当描述为「最后一个 commit → 当前工作区」的**整体 diff**，而不应该提及本次实现过程中的尝试、报错、排查、返工或中间修正的迭代过程；
   - 若该 commit 能够关闭一个 issue，请在提交消息末尾加上 `close #xxx` 以确保 issue 关闭时能够与此 commit 关联，而不是使用 `fix(#xxx): xxx` 等格式。
3. 本仓库是上游的 fork：`origin` 为本人仓库，`upstream` 为上游官方仓库。同步上游修复时使用 `cherry-pick`（保留原作者署名），不要直接把 `main` 重置成上游状态，以免丢掉本仓库的增强提交。
