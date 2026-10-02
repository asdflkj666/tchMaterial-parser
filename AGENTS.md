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
2. **失败先放过、末尾再裁决**：首轮失败不做原地重试，直接继续下一个文件；批次末尾用 `classify_failures()` 区分「资源不可用」与「疑似限流」——判据是失败之后是否还有别的文件成功（`controller.has_success_since()`，基于成功计数而非时间戳，因为 Windows 上 `time.monotonic()` 精度仅约 15ms）。只对「疑似限流」的再试一次，重试过要标记 `state["retried"]` 并重新裁决。
3. **分类必须在 `controller.reset()` 之前完成**，否则探针信号会被清空，判定反转。
4. **暂停按文件边界生效**：进行中的文件会下完，未开始的任务在 `controller.wait_to_start()` 处阻塞；取消则在分块写入点抛 `DownloadCancelled` 并清理 `.tmp`。
5. **下载设置**统一在 `config.DOWNLOAD_SETTING_SPECS` 中声明（含默认值、范围、说明），界面由 `ui/settings_window.py` 自动生成；`min_request_interval` 与 `http400_retries` 通过 `download_panel.apply_download_settings()` 同步到模块变量 `_MIN_REQUEST_INTERVAL` / `_400_RETRY_DELAYS`——这两个变量被测试直接 patch，**不要删除或内联**。
6. **配置与 UI 的解耦**：设置窗口只写 `config`，不直接依赖下载模块；保存成功后由 `config.on_download_settings_changed()` 通知，接线放在 `app.py`。新增需要「保存后立即生效」的配置项时沿用这条路径。
7. **界面控件句柄**统一放在 `download_panel.widgets`（`PanelWidgets` 容器）里，由 `app.py` 通过 `bind_widgets()` 注入；新增控件请在容器里加字段，不要再引入模块级全局变量。
8. **日志**统一走 `download_panel.log_message()`（可在任意线程调用，内部切回主线程），失败原因要带 HTTP 状态码的中文解释（`HTTP_STATUS_HINTS` / `status_hint()`）。

## Git 操作

1. 除非用户要求，否则不要执行 commit 与 push。
2. 若被用户要求写 commit：
   - 请只生成遵循「**Conventional Commit**」的提交消息，内容应当描述为「最后一个 commit → 当前工作区」的**整体 diff**，而不应该提及本次实现过程中的尝试、报错、排查、返工或中间修正的迭代过程；
   - 若该 commit 能够关闭一个 issue，请在提交消息末尾加上 `close #xxx` 以确保 issue 关闭时能够与此 commit 关联，而不是使用 `fix(#xxx): xxx` 等格式。
