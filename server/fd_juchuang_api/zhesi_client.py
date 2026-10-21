"""哲思结构卡契约客户端（task 3.1）。

消费哲思侧版本化契约 GET /api/v1/contract/cards?consumer=juchuang（design D1：
纯消费侧）。授权在哲思侧 grants 表——用户令牌原样透传（Bearer = 用户自己的
token，require_user 解出的那枚 JWT），剧创不持有任何服务级凭据。

三态语义（spec「授权边界继承」+「无哲思模式」）：
- 成功 → (cards, tensions)，字段集按哲思 contract_version="1" 消费；
- 401/403 → NotAuthorized（未授权：进入无哲思模式并如实上报 reason）；
- 5xx / 超时 / 网络错 / 契约版本不识别 / 坏负载 → Unavailable（契约不可达：降级）。

铁律：单次调用，8s 超时，无重试堆栈（照 llm.py 先例，失败就交给调用方降级）。
"""

from __future__ import annotations

import os

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8010"
CONTRACT_PATH = "/api/v1/contract/cards"
CONSUMER = "juchuang"
SUPPORTED_CONTRACT_VERSIONS = ("1",)
TIMEOUT_SECONDS = 8.0


class NotAuthorized(RuntimeError):
    """哲思侧未授权（401/403）：进入无哲思模式，reason 如实上报。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Unavailable(RuntimeError):
    """契约不可达（5xx/超时/坏负载/版本不识别）：降级，创作不阻断。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def base_url() -> str:
    return os.environ.get("FD_JUCHUANG_ZHESI_BASE", DEFAULT_BASE_URL).rstrip("/")


def fetch_cards(token: str) -> tuple[list[dict], list[dict]]:
    """按契约取授权范围内的立场卡与张力对；返回 (cards, tensions)。

    抛 NotAuthorized / Unavailable，绝不重试。token 是用户自己的令牌，
    由调用方从 Authorization 头原样取得后传入（授权裁决在哲思侧）。
    """
    try:
        resp = httpx.get(
            f"{base_url()}{CONTRACT_PATH}",
            params={"consumer": CONSUMER},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:  # 超时/连接失败等，一律归一为不可达
        raise Unavailable(f"zhesi unreachable: {type(exc).__name__}: {exc}") from exc

    if resp.status_code in (401, 403):
        detail = ""
        try:
            detail = str(resp.json().get("detail", ""))
        except ValueError:
            pass
        raise NotAuthorized(f"zhesi http {resp.status_code}: {detail}".strip())
    if resp.status_code >= 400:
        raise Unavailable(f"zhesi http {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise Unavailable("zhesi contract: invalid json") from exc

    version = str(data.get("contract_version", ""))
    if version not in SUPPORTED_CONTRACT_VERSIONS:
        raise Unavailable(f"zhesi contract_version {version!r} not supported")

    cards = data.get("cards")
    tensions = data.get("tensions", [])  # 未授权 tension 卡类时哲思省略该字段
    if not isinstance(cards, list) or not isinstance(tensions, list):
        raise Unavailable("zhesi contract: cards/tensions not lists")
    return cards, tensions
