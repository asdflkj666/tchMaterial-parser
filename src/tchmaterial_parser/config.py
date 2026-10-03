# -*- coding: utf-8 -*-
# 本地配置的读写（Windows 用注册表，其余平台用 JSON 文件）与登录凭据的维护
#
# 鉴权相关三项：
# - access_token：X-ND-AUTH 的 MAC id，也用于 Authorization: Bearer
# - mac_key：官网 HMAC 密钥；没有它就只能生成占位头
# - token_diff：官网 Fe(diff) 的时钟差（毫秒），只影响 nonce 时间戳
# 不要把 refresh_token 写入配置。旧用户可能只有 AccessToken 注册表值，加载时 mac_key 为空是正常的。

import json, os
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from .auth import TokenCredentials, parse_token_input
from .network import headers, sync_session_headers
from .platform_utils import os_name, print_error, winreg

access_token: str | None = None
mac_key: str | None = None
token_diff: int = 0 # 与 UC Token JSON 的 diff 对应，单位毫秒

REGISTRY_PATH = "Software\\tchMaterial-parser" # Windows 下存放配置的注册表键
CONFIG_KEYS = { # 配置项名称到注册表值名称的映射（JSON 文件直接使用配置项名称）
    "access_token": "AccessToken",
    "mac_key": "MacKey",
    "token_diff": "TokenDiff",
    "theme": "Theme",
    "download_workers": "DownloadWorkers",
    "min_request_interval": "MinRequestInterval",
    "circuit_threshold": "CircuitThreshold",
    "cooldown_seconds": "CooldownSeconds",
    "retry_rounds": "RetryRounds",
    "http400_retries": "Http400Retries",
    "download_timeout": "DownloadTimeout",
}

class DownloadSettingSpec(NamedTuple):
    """一项下载技术配置的元数据：默认值、取值范围与界面展示信息。"""

    key: str
    label: str
    default: int | float
    minimum: int | float
    maximum: int | float
    integer: bool = False
    unit: str = ""
    description: str = ""

DOWNLOAD_SETTING_SPECS: tuple[DownloadSettingSpec, ...] = (
    DownloadSettingSpec("download_workers", "并发下载数", 3, 1, 6, True, "个", "同时下载的文件数量。私有 CDN 对并发敏感，过大易触发限流。"),
    DownloadSettingSpec("min_request_interval", "请求最小间隔", 0.2, 0.1, 2.0, False, "秒", "两次请求之间的最小等待时间。"),
    DownloadSettingSpec("circuit_threshold", "限流触发阈值", 3, 2, 10, True, "个文件", "60 秒内有这么多个“不同文件”下载失败时，判定为限流并进入冷却（同一文件反复失败只算一次）。"),
    DownloadSettingSpec("cooldown_seconds", "冷却时长", 180, 30, 1800, True, "秒", "判定限流后整批暂停的基准时长；连续触发会自动翻倍（上限 30 分钟）。"),
    DownloadSettingSpec("retry_rounds", "疑似限流文件末尾重试次数", 1, 0, 3, True, "次", "批次末尾对“疑似限流”的失败文件再重试的次数；失败时若前后没有别的文件也在失败（孤立失败），视为该文件自身不可用，不会重试。"),
    DownloadSettingSpec("http400_retries", "400 错误重试次数", 2, 0, 5, True, "次", "同一地址遇到 400 时的退避重试次数（换镜像前）。"),
    DownloadSettingSpec("download_timeout", "下载数据超时", 60, 10, 300, True, "秒", "等待服务器发送下一段数据的最大时长。"),
)

CIRCUIT_FAILURE_WINDOW = 60.0 # 限流失败的统计窗口（秒）
COOLDOWN_MAX_SECONDS = 1800 # 冷却时长递增的封顶（秒）
COOLDOWN_ESCALATION_RESET = 600.0 # 距上次触发超过该时长（秒）后，冷却倍数重新从 1 开始

download_settings: dict[str, int | float] = {spec.key: spec.default for spec in DOWNLOAD_SETTING_SPECS}

# 下载设置变更后的回调。由 app 层把 config 与下载模块接起来，
# 这样设置窗口只需要写 config，不必反过来依赖下载面板。
_download_settings_listeners: list[Callable[[], None]] = []

def on_download_settings_changed(listener: Callable[[], None]) -> None:
    """注册一个在下载设置保存成功后调用的回调（重复注册同一函数不会重复添加）。"""
    if listener not in _download_settings_listeners:
        _download_settings_listeners.append(listener)

def _parse_setting_value(spec: DownloadSettingSpec, raw: str) -> int | float:
    """把字符串形式的配置值解析为数字并校验范围；不合法时抛出 ValueError。"""
    text = raw.strip()
    if not text:
        raise ValueError(f"“{spec.label}”不能为空。")
    try:
        value: float = float(text)
    except ValueError:
        raise ValueError(f"“{spec.label}”必须是数字。") from None
    if value != value or value in (float("inf"), float("-inf")): # 排除 nan / inf
        raise ValueError(f"“{spec.label}”必须是有效数字。")
    if spec.integer and value != int(value):
        raise ValueError(f"“{spec.label}”必须是整数。")
    value = int(value) if spec.integer else value
    if value < spec.minimum or value > spec.maximum:
        unit = f" {spec.unit}" if spec.unit else ""
        raise ValueError(f"“{spec.label}”需在 {spec.minimum} 到 {spec.maximum}{unit} 之间。")
    return value

def load_download_settings(saved_config: dict[str, str]) -> None:
    """从已读取的配置中解析下载技术配置；缺失或非法时保留默认值。"""
    for spec in DOWNLOAD_SETTING_SPECS:
        raw = saved_config.get(spec.key)
        if raw is None:
            continue
        try:
            download_settings[spec.key] = _parse_setting_value(spec, raw)
        except ValueError as error:
            print_error(error)

def set_download_settings(values: dict[str, str]) -> str:
    """校验并保存全部下载技术配置，成功后立即生效。"""
    parsed: dict[str, int | float] = {}
    for spec in DOWNLOAD_SETTING_SPECS:
        raw = values.get(spec.key)
        if raw is None:
            raise ValueError(f"缺少配置项 “{spec.label}”。")
        parsed[spec.key] = _parse_setting_value(spec, str(raw))

    save_config(**{key: str(value) for key, value in parsed.items()})
    download_settings.update(parsed)
    for listener in _download_settings_listeners: # 通知下载模块同步派生参数
        listener()
    return "下载设置已保存，将在之后的下载中生效。\n" + config_location()

def reset_download_settings() -> dict[str, int | float]:
    """恢复全部下载技术配置的默认值（只改内存，不落盘；由设置窗口回填后再保存）。"""
    defaults = {spec.key: spec.default for spec in DOWNLOAD_SETTING_SPECS}
    return defaults

def config_file_path() -> Path | None: # 获取配置文件路径
    if os_name == "Windows": # 在 Windows 上，配置存放于 %LOCALAPPDATA%\tchMaterial-parser\data.json（此处为备用）
        return Path(
            os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local",
            "tchMaterial-parser",
            "data.json",
        )
    elif os_name in ("Linux", "Android"): # 在 Linux 上，配置存放于 ~/.config/tchMaterial-parser/data.json
        return Path.home() / ".config" / "tchMaterial-parser" / "data.json"
    elif os_name == "Darwin": # 在 macOS 上，配置存放于 ~/Library/Application Support/tchMaterial-parser/data.json
        return Path.home() / "Library" / "Application Support" / "tchMaterial-parser" / "data.json"

def config_location() -> str: # 获取配置存放位置的描述文本，用于提示用户
    if os_name == "Windows":
        return f"已写入注册表：HKEY_CURRENT_USER\\{REGISTRY_PATH}"
    elif os_name in ("Linux", "Android"):
        return "已保存至文件：~/.config/tchMaterial-parser/data.json"
    elif os_name == "Darwin":
        return "已保存至文件：~/Library/Application Support/tchMaterial-parser/data.json"
    else:
        return "本工具尚未支持该操作系统下 Access Token 的持久化，下次启动时仍需手动输入 Access Token。"

def load_config() -> dict[str, str]: # 读取本地存储的配置
    loaded: dict[str, str] = {}

    if os_name == "Windows": # 在 Windows 上，从注册表读取
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_READ) as key:
                for name, value_name in CONFIG_KEYS.items():
                    try:
                        value, _ = winreg.QueryValueEx(key, value_name)
                    except FileNotFoundError: # 该配置项尚未写入
                        continue
                    if not isinstance(value, str):
                        print_error(TypeError(f"配置项 {name} 必须是字符串"))
                        continue
                    loaded[name] = value
            return loaded
        except FileNotFoundError: # 注册表键不存在，即从未保存过配置
            return {}
        except Exception as e:
            print_error(e)
            return {}

    try:
        target_file = config_file_path() # 在其他平台上，从 JSON 文件读取
        if not target_file or not os.path.exists(target_file): # 文件不存在表示尚未保存过配置
            return {}
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print_error(TypeError("配置文件的根节点必须是对象"))
            return {}
        for name in CONFIG_KEYS:
            if name not in data:
                continue
            value = data[name]
            if not isinstance(value, str):
                print_error(TypeError(f"配置项 {name} 必须是字符串"))
                continue
            loaded[name] = value
        return loaded
    except Exception as e:
        print_error(e)
        return {}

def save_config(**updates: str) -> None: # 保存配置，并与已有配置合并
    if os_name == "Windows": # 在 Windows 上，写入注册表
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH) as key:
            for name, value in updates.items():
                winreg.SetValueEx(key, CONFIG_KEYS[name], 0, winreg.REG_SZ, value)
        return

    target_file = config_file_path() # 在其他平台上，写入 JSON 文件
    data = load_config() # 先读取已有配置，避免覆盖其他配置项
    data.update(updates)
    os.makedirs(os.path.dirname(target_file), exist_ok=True)
    with open(target_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def apply_static_headers() -> None:
    """更新全局占位头。私有下载不要用这份 X-ND-AUTH，应走 network.request_headers。"""
    headers["Authorization"] = f"Bearer {access_token or '0'}"
    headers["X-ND-AUTH"] = f'MAC id="{access_token or "0"}",nonce="0",mac="0"'
    sync_session_headers() # 已经建好的 session 不会自动跟上这里对 headers 的原地修改

def apply_credentials(credentials: TokenCredentials) -> None:
    """写入内存中的凭据并刷新占位头。空 access_token 视为未登录。"""
    global access_token, mac_key, token_diff
    access_token = credentials.access_token or None
    mac_key = credentials.mac_key
    token_diff = credentials.diff
    apply_static_headers()

def load_access_token(saved_config: dict[str, str]) -> None: # 从已读取的配置中加载登录凭据
    # 参数不要叫 config，避免在模块内部遮蔽模块名
    token = saved_config.get("access_token") or ""
    stored_mac = saved_config.get("mac_key") or ""
    try:
        stored_diff = int(saved_config.get("token_diff") or 0)
    except ValueError:
        stored_diff = 0
    apply_credentials(TokenCredentials(token, stored_mac or None, stored_diff))

def set_access_token(raw: str) -> str: # 校验三项 JSON 并保存；空内容则清除已保存的登录凭据
    credentials = parse_token_input(raw)
    apply_credentials(credentials)
    save_config(
        access_token=credentials.access_token,
        mac_key=credentials.mac_key or "",
        token_diff=str(credentials.diff),
    )
    if not credentials.access_token:
        return f"登录凭据已清除。\n{config_location()}"
    return f"登录凭据已保存！\n{config_location()}"
