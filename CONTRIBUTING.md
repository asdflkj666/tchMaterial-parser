# 贡献者指南

本仓库是 [happycola233/tchMaterial-parser](https://github.com/happycola233/tchMaterial-parser) 的个人 fork。

> [!IMPORTANT]
> **建议把改动交给 AI 处理。**
> 本仓库的代码由 AI 生成与维护，人读起来的性价比很低（参见 [README](README.md) 开头的警告）。你负责提出需求、验收结果，剩下的交给 AI。

## 交给 AI 做的事

| 你想做的事 | 直接说需求即可 |
| :-- | :-- |
| 加功能 / 改行为 | 「改一下 xxx，我希望 …」 |
| 排查问题 | 「下载时出现 …，看下是哪里的问题」 |
| 跑测试与检查 | 「跑一遍测试和 flake8」 |
| 写提交信息 | 「按 Conventional Commit 写提交消息」 |

报错信息、截图、复现步骤**原样贴过去**就行，不需要自己先定位——定位和验证本身就是 AI 的活。

## 人来做的事

1. **说清需求**：你遇到的实际问题，比“应该怎么实现”更有价值。
2. **验收**：把程序跑起来点一遍，确认行为符合预期。**实际运行由人来测**，别让 AI 在沙箱里自我验证。
3. **决定取舍**：默认值定多少、要不要打包发布、要不要引入新依赖，这类取舍由你拍板。

## 如果非要自己动手（不推荐，仅供参考）

```sh
# 需要 Python 3.10 或更高版本
python -m pip install .        # 安装依赖并注册包
python ./src/main.py           # 启动程序

python -m pip install pytest flake8
python -m pytest               # 运行单元测试
python -m flake8 . --count --select=E9,F63,F7,F82 --statistics
```

修改打包配置、资源文件或程序入口时，额外验证 PyInstaller 构建：

```sh
python -m pip install pyinstaller
pyinstaller ./tchMaterial-parser.spec
```

约定（AI 通常会自动遵守，人改的话请照做）：

- **4 空格**缩进、**`snake_case`** 命名、字符串默认用**双引号**、不出现尾随空格；
- 保持 **Windows / Linux / macOS** 跨平台兼容；
- 涉及 UI 的改动，同时检查**浅色与深色模式**；
- 意图不明显的业务逻辑写**简短中文注释**，能从代码本身读懂的不要注释；
- 校验放在**系统边界**（用户输入、文件系统、网络请求），不为理论上不可能的内部状态加兜底；
- 改动下载/限流相关逻辑前，先读 [AGENTS.md](./AGENTS.md) 里的「下载与限流约定」。

## 红线

- **不要公开 Access Token**：Issue、提交信息、截图、代码里都不要出现。
- 改动仅用于个人学习与教学参考，请遵守国家中小学智慧教育平台的服务条款与资源版权。
- 本 fork 是个人的分支，**不接受上游式的 Issue / PR 流程**；原版功能（解析、下载、书签等）的问题请到[原项目](https://github.com/happycola233/tchMaterial-parser/issues)反馈。

## 上游

原项目由 [@happycola233](https://github.com/happycola233) 及众多贡献者开发维护，本 fork 的绝大部分代码来自他们。
