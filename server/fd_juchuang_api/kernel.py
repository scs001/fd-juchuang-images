"""哲思内核消费路由（task 3.2/3.3）：映射表 + 注入 + 降级独立模式。

路由（全部 require_user）：
- POST /api/v1/kernel/link       尝试取卡：成功缓存进 kernel_state(mode=linked) 并返回
                                  映射摘要；403/不可达 → mode=standalone + reason
                                  （spec 降级语义：创作不阻断，明示当前模式）。
- GET  /api/v1/kernel/status     当前模式 / 缓存卡数 / 最近错误。
- POST /api/v1/kernel/inject/{project_id}
                                  把映射产物写进剧本项目：张力→场次 conflict、
                                  立场卡→角色 stance；调 screenplay.py 的领域函数
                                  （import 其路由函数与校验模型，不绕过其校验；
                                  无对应场次/角色先创建骨架）。项目不存在 404。
                                  幂等：同 zhesi ref 不重复写；恢复补挂 = linked 后
                                  对已有项目重跑 inject。

映射表（design D5）：哲思数据 → 剧创素材的映射是显式版本化配置（纯数据 +
纯函数），哲思契约升级或剧创模板演进互不牵连：
- 张力对 → 剧本冲突元数据 {positions, source, zhesi_tension_ref}（spec「张力对
  映射核心冲突」：冲突双方立场、张力来源可溯到哲思卡）
- 立场卡 → 角色立场卡 stance={position, reasons, source:"zhesi:<card_id>"}
- strongest_objection → 对手戏弹药（随角色立场卡 reasons 落库，见下）
- as_of 保留（立场时效可溯，随 reasons 落库）

落库口径（受 screenplay 校验模型约束，经其 ConflictModel/StanceModel 写入）：
- 场次 conflict.positions = 双方立场串（各=「问题：立场」）；conflict.source =
  "zhesi:tension:<id> | <哲学史背景>"——哲思卡 ID 经 source 可溯（校验模型
  extra=forbid，不塞额外字段，不绕过校验）。
- 角色 stance = {position, reasons, source}；reasons 内保留稳定度、对手戏弹药
  （最强反驳）与 as_of，全部经 StanceModel 校验落库。

存储：与 screenplay.py 共库（env FD_JUCHUANG_DB，默认 ~/.fd-juchuang/juchuang.db），
本模块自建表 kernel_state。降级语义细节：NotAuthorized 清缓存（授权边界收回即
停止消费）；Unavailable 保留缓存（契约恢复前的最后已知映射仍可用于补挂注入）；
两者都置 mode=standalone 并在 /status 如实明示。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from . import zhesi_client
from .zhesi_client import NotAuthorized, Unavailable

# ---- 鉴权接线（照 screenplay.py 先例：personal 底座未交付时的降级兜底） ----

try:  # 正式路径：auth.py 的 require_user（含审计留痕）
    from .auth import require_user
except Exception:  # noqa: BLE001 —— personal 底座未交付时的降级兜底，交付后本分支不触发
    def require_user(request: Request) -> str:  # type: ignore[misc]
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if token:
            for var in ("FD_JUCHUANG_AUTH_DEV_TOKENS", "FD_JUCHUANG_AUTH_DEV_TOKENS"):
                for pair in os.environ.get(var, "").split(","):
                    if "=" in pair and pair.split("=", 1)[0].strip() == token:
                        return pair.split("=", 1)[1].strip()
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")

router = APIRouter(prefix="/api/v1/kernel", tags=["kernel"])

# ---------------------------------------------------------------------------
# D5 映射表（版本化；纯数据 + 纯函数）
# ---------------------------------------------------------------------------

KERNEL_MAP_VERSION = "1"

KERNEL_MAP: dict[str, Any] = {
    "version": KERNEL_MAP_VERSION,
    # 张力对 → 剧本冲突元数据（落在场次 conflict 字段，D2：注入点是元数据不是提示词）
    "tension_to_conflict": {
        "ref_prefix": "zhesi:tension:",
        "positions": "card_ids 反查立场卡 → [「问题：立场」×2]",
        "source": "zhesi_tension_ref + 哲学史背景（卡 ID 经 source 可溯）",
        "policy": "一个张力一场戏：每个张力对落到自己的骨架场次",
    },
    # 立场卡 → 角色立场卡（source 指回哲思卡 ID，spec「立场卡派生角色」）
    "stance_card_to_character": {
        "ref_prefix": "zhesi:",
        "stance_fields": ["position", "reasons", "source"],
        "preserved_in_reasons": ["stability", "ammunition", "as_of"],
    },
    # strongest_objection → 对手戏弹药（随角色立场卡 reasons 落库）
    "objection_to_ammunition": {"field": "ammunition"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _position_text(card: dict) -> str:
    """立场卡 → 冲突一方立场串（ConflictModel.positions 元素）。"""
    question = (card.get("question") or "").strip() or "未命名问题"
    position = (card.get("position") or "").strip() or "未知立场"
    return f"{question}：{position}"


def map_tension_to_conflict(tension: dict, cards_by_id: dict[str, dict]) -> dict | None:
    """张力对 → 冲突元数据。双方立场从 card_ids 反查立场卡；凑不满两方（对方卡
    未授权/已封存）返回 None（宁缺毋滥，不写残缺冲突）。"""
    sides = []
    for card_id in tension.get("card_ids", []):
        card = cards_by_id.get(card_id)
        if card:
            sides.append(
                {
                    "card_id": card_id,
                    "question": card.get("question", ""),
                    "position": card.get("position", ""),
                }
            )
    if len(sides) < 2:
        return None
    zhesi_tension_ref = f"zhesi:tension:{tension.get('id', '')}"
    return {
        "positions": [_position_text(s) for s in sides[:2]],
        "source": f"{zhesi_tension_ref} | {tension.get('source', '')}".strip(" |"),
        "zhesi_tension_ref": zhesi_tension_ref,
        "description": tension.get("description", ""),
        "sides": sides[:2],
    }


def map_card_to_stance(card: dict) -> dict:
    """立场卡 → 角色立场卡映射产物。

    strongest_objection → 对手戏弹药、as_of 时效：screenplay 的 StanceModel
    extra=forbid（只有 position/reasons/source），故随 reasons 一并落库保留。
    """
    card_id = card.get("id", "")
    question = card.get("question", "")
    position = card.get("position", "")
    stability = card.get("stability", "")
    ammunition = card.get("strongest_objection", "")
    as_of = card.get("as_of", "")
    parts = [f"源自哲思立场卡「{question}」：持「{position}」"]
    if stability:
        parts.append(f"稳定度 {stability}")
    if ammunition:
        parts.append(f"对手戏弹药（最强反驳）：{ammunition}")
    if as_of:
        parts.append(f"as_of {as_of}")
    name = f"立场·{position}" if position else f"立场·{card_id}"
    return {
        "zhesi_card_ref": f"zhesi:{card_id}",
        "name": name[:40],
        "stance": {
            "position": position,
            "reasons": "；".join(parts),
            "source": f"zhesi:{card_id}",
        },
        "ammunition": ammunition,
        "as_of": as_of,
    }


def build_mapped_products(cards: list[dict], tensions: list[dict]) -> dict:
    """契约负载 → 全部映射产物（link 摘要与 inject 共用同一套纯函数）。"""
    cards_by_id = {c.get("id", ""): c for c in cards}
    conflicts, unmappable = [], []
    for t in tensions:
        mapped = map_tension_to_conflict(t, cards_by_id)
        if mapped is None:
            unmappable.append(f"zhesi:tension:{t.get('id', '')}")
        else:
            conflicts.append(mapped)
    return {
        "conflicts": conflicts,
        "stances": [map_card_to_stance(c) for c in cards],
        "unmappable_tensions": unmappable,
    }


# ---------------------------------------------------------------------------
# 存储：kernel_state（与 screenplay 共库 env FD_JUCHUANG_DB）
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = str(Path.home() / "fd-juchuang" / "juchuang.db")

_STATE_DDL = """
CREATE TABLE IF NOT EXISTS kernel_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL CHECK (mode IN ('linked', 'standalone')),
    cards_cache TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
)
"""


def connect() -> sqlite3.Connection:
    path = os.environ.get("FD_JUCHUANG_DB", "").strip() or DEFAULT_DB_PATH
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(_STATE_DDL)
    conn.commit()


def get_state(conn: sqlite3.Connection, user_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM kernel_state WHERE user_id=?", (user_id,)
    ).fetchone()
    if not row:
        return None
    try:
        cache = json.loads(row["cards_cache"] or "{}")
    except ValueError:
        cache = {}
    return {
        "user_id": row["user_id"],
        "mode": row["mode"],
        "cards_cache": cache if isinstance(cache, dict) else {},
        "updated_at": row["updated_at"],
    }


def set_state(
    conn: sqlite3.Connection,
    user_id: str,
    mode: str,
    cards_cache: dict | None,
    last_error: str | None,
) -> None:
    """upsert 用户内核态。cards_cache 传 None 且已有缓存时保留原缓存
    （Unavailable 降级不清数据）；显式传 {} 才清空（NotAuthorized 授权收回）。"""
    prev = get_state(conn, user_id)
    if cards_cache is None:
        cards_cache = (prev or {}).get("cards_cache") or {}
    envelope = dict(cards_cache)
    envelope["last_error"] = last_error
    envelope["last_error_at"] = _now() if last_error else None
    conn.execute(
        "INSERT INTO kernel_state (user_id, mode, cards_cache, updated_at)"
        " VALUES (?,?,?,?)"
        " ON CONFLICT(user_id) DO UPDATE SET"
        " mode=excluded.mode, cards_cache=excluded.cards_cache,"
        " updated_at=excluded.updated_at",
        (user_id, mode, json.dumps(envelope, ensure_ascii=False), _now()),
    )
    conn.commit()


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


# ---------------------------------------------------------------------------
# screenplay 域适配（inject 经 screenplay.py 的路由函数与校验模型写入，不绕过校验）
# ---------------------------------------------------------------------------


def _screenplay():
    """延迟 import：link/status 不依赖剧本域；inject 时才加载。"""
    from . import screenplay

    return screenplay


def _scene_has_ref(scene: dict, ref: str) -> bool:
    conflict = scene.get("conflict")
    return isinstance(conflict, dict) and ref in (conflict.get("source") or "")


def _character_has_ref(character: dict, ref: str) -> bool:
    stance = character.get("stance")
    return isinstance(stance, dict) and stance.get("source") == ref


def _inject_conflicts(sp, user_id: str, project_id: str, conflicts: list[dict]) -> list[dict]:
    """张力 → 场次 conflict（一张力一场戏，无该场次先建骨架）。

    幂等：项目内已有 conflict.source 含同一 zhesi_tension_ref 的场次则跳过，
    不重复写、不覆盖用户手写内容。
    """
    out: list[dict] = []
    scenes = sp.list_scenes(project_id, user_id)  # 归属校验在 screenplay 侧（404）
    for conflict in conflicts:
        ref = conflict["zhesi_tension_ref"]
        existing = next((s for s in scenes if _scene_has_ref(s, ref)), None)
        if existing is not None:
            out.append(
                {
                    "scene_id": existing["id"],
                    "title": existing.get("title", ""),
                    "zhesi_tension_ref": ref,
                    "action": "skipped",
                }
            )
            continue
        title = (conflict.get("description") or ref)[:60]
        scene_in = sp.SceneIn(
            title=title,
            synopsis=f"哲思张力对场次（{ref}）：{conflict.get('description', '')}",
            conflict=sp.ConflictModel(
                positions=tuple(conflict["positions"]),
                source=conflict["source"],
            ),
        )
        created = sp.create_scene(project_id, scene_in, user_id)
        out.append(
            {
                "scene_id": created["id"],
                "title": created.get("title", ""),
                "zhesi_tension_ref": ref,
                "action": "created",
            }
        )
    return out


def _inject_stances(sp, user_id: str, project_id: str, stances: list[dict]) -> list[dict]:
    """立场卡 → 角色 stance（无该角色先建骨架；appearance 为待定占位要素集）。

    幂等：项目内已有 stance.source == 同一 zhesi 卡 ref 的角色则跳过。
    """
    out: list[dict] = []
    characters = sp.list_characters(project_id, user_id)
    for product in stances:
        ref = product["zhesi_card_ref"]
        existing = next((c for c in characters if _character_has_ref(c, ref)), None)
        if existing is not None:
            out.append(
                {
                    "character_id": existing["id"],
                    "name": existing.get("name", ""),
                    "zhesi_card_ref": ref,
                    "action": "skipped",
                }
            )
            continue
        character_in = sp.CharacterIn(
            name=product["name"],
            appearance={"年龄感": "待定", "着装": "待定"},  # 骨架占位，编辑器再补
            stance=sp.StanceModel(**product["stance"]),
        )
        created = sp.create_character(project_id, character_in, user_id)
        out.append(
            {
                "character_id": created["id"],
                "name": created.get("name", ""),
                "zhesi_card_ref": ref,
                "action": "created",
            }
        )
    return out


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("/link")
def link(request: Request, user_id: str = Depends(require_user)) -> dict:
    """尝试取卡并缓存。成功返回映射摘要；失败降级 standalone + reason（200，
    创作不阻断；spec「无哲思模式」）。"""
    conn = connect()
    try:
        migrate(conn)
        token = _bearer_token(request)
        try:
            cards, tensions = zhesi_client.fetch_cards(token)
        except NotAuthorized as exc:
            set_state(conn, user_id, "standalone", {}, f"not_authorized: {exc.reason}")
            return {
                "mode": "standalone",
                "reason": f"not_authorized: {exc.reason}",
                "kernel_map_version": KERNEL_MAP_VERSION,
                "cached_cards": 0,
                "note": "未在哲思侧对 juchuang 授权：已进入无哲思模式，创作不阻断；"
                "在哲思侧授权后重跑 /link 再 /inject 可补挂。",
            }
        except Unavailable as exc:
            set_state(conn, user_id, "standalone", None, f"unavailable: {exc.reason}")
            prev = get_state(conn, user_id) or {}
            cache = prev.get("cards_cache") or {}
            return {
                "mode": "standalone",
                "reason": f"unavailable: {exc.reason}",
                "kernel_map_version": KERNEL_MAP_VERSION,
                "cached_cards": len(cache.get("cards", []) or []),
                "note": "哲思契约不可达：已降级为无哲思模式，创作不阻断；"
                "契约恢复后重跑 /link 再 /inject 可补挂。",
            }
        set_state(
            conn,
            user_id,
            "linked",
            {"cards": cards, "tensions": tensions, "fetched_at": _now()},
            None,
        )
        products = build_mapped_products(cards, tensions)
        return {
            "mode": "linked",
            "kernel_map_version": KERNEL_MAP_VERSION,
            "cards": len(cards),
            "tensions": len(tensions),
            "conflicts": [
                {
                    "zhesi_tension_ref": c["zhesi_tension_ref"],
                    "positions": list(c["positions"]),
                    "source": c["source"],
                }
                for c in products["conflicts"]
            ],
            "stances": [
                {
                    "zhesi_card_ref": s["zhesi_card_ref"],
                    "position": s["stance"]["position"],
                    "as_of": s["as_of"],
                }
                for s in products["stances"]
            ],
            "unmappable_tensions": products["unmappable_tensions"],
        }
    finally:
        conn.close()


@router.get("/status")
def status(user_id: str = Depends(require_user)) -> dict:
    """当前模式 / 缓存卡数 / 最近错误（降级明示）。"""
    conn = connect()
    try:
        migrate(conn)
        state = get_state(conn, user_id)
        cache = (state or {}).get("cards_cache") or {}
        return {
            "user_id": user_id,
            "mode": (state or {}).get("mode", "standalone"),
            "cached_cards": len(cache.get("cards", []) or []),
            "cached_tensions": len(cache.get("tensions", []) or []),
            "last_error": cache.get("last_error"),
            "updated_at": (state or {}).get("updated_at"),
            "kernel_map_version": KERNEL_MAP_VERSION,
            "zhesi_base": zhesi_client.base_url(),
        }
    finally:
        conn.close()


@router.post("/inject/{project_id}")
def inject(project_id: str, user_id: str = Depends(require_user)) -> dict:
    """把缓存的映射产物写进剧本项目（幂等；项目不存在 404，由 screenplay 侧
    归属校验抛出）。

    降级语义：无缓存（从未 link 或授权收回）时明示 standalone 并空手返回，
    不阻断创作；Unavailable 降级保留的最后缓存仍可注入（恢复补挂面）。
    """
    try:
        sp = _screenplay()
    except ImportError as exc:  # 剧本域未就绪：不崩服务，如实上报
        raise HTTPException(503, f"剧本域模块不可用: {exc}") from exc

    # screenplay 的项目 id 口径（int 主键）与本路由的路径参数（str）对齐：
    # 纯数字串转 int，其余原样（兼容字串 id 方案）
    pid = int(project_id) if project_id.isdigit() else project_id
    sp.get_project(pid, user_id)  # 404 归属校验在 screenplay 侧

    kconn = connect()
    try:
        migrate(kconn)
        state = get_state(kconn, user_id)
    finally:
        kconn.close()
    cache = (state or {}).get("cards_cache") or {}
    cards = cache.get("cards") or []
    tensions = cache.get("tensions") or []
    if (state or {}).get("mode") != "linked" and not cards:
        return {
            "mode": "standalone",
            "reason": cache.get("last_error") or "never linked",
            "injected": {"scenes": [], "characters": [], "counts": {}},
            "note": "无哲思数据可注入（无哲思模式）；授权并 /link 后重跑本接口可补挂。",
        }

    products = build_mapped_products(cards, tensions)
    scenes = _inject_conflicts(sp, user_id, pid, products["conflicts"])
    characters = _inject_stances(sp, user_id, pid, products["stances"])
    return {
        "mode": (state or {}).get("mode", "standalone"),
        "kernel_map_version": KERNEL_MAP_VERSION,
        "project_id": pid,
        "injected": {
            "scenes": scenes,
            "characters": characters,
            "counts": {
                "scenes_created": sum(1 for s in scenes if s["action"] == "created"),
                "scenes_skipped": sum(1 for s in scenes if s["action"] == "skipped"),
                "characters_created": sum(1 for c in characters if c["action"] == "created"),
                "characters_skipped": sum(1 for c in characters if c["action"] == "skipped"),
            },
            "unmappable_tensions": products["unmappable_tensions"],
        },
    }
