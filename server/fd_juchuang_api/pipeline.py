"""AI 底料管线（task 4.1/4.2/4.3）：剧本 → 分镜 → 三形态提示词。

三级结构化产物（design D3），LLM 只做级间转换、人在环上可逐级修改：
  剧本（screenplay 模块的场次/台词/角色要素集）
    → 分镜 storyboard（镜头表：每镜一行，确定性引擎必做，LLM 仅润色 visual/action）
    → 提示词 promptset（image / video / narrative 三形态，schema_version 版本化）

- 确定性底座：无 FD_JUCHUANG_LLM_API_KEY 时全流程可用（按台词行切镜，句长定景别，
  字数定时长）；LLM 为可选增强，任何失败回退确定性版并标 engine。
- 角色一致性（design D4）：含某角色的镜头，image/video 提示词自动注入该角色
  appearance 要素集原文 + character_id，跨镜头同角色要素集严格一致。

存储：共库 FD_JUCHUANG_DB（默认 juchuang.db），本模块自建两张表：
  storyboard(id, scene_id INTEGER, idx, shot JSON, created_at)
  promptset(id, storyboard_id INTEGER, form, payload JSON, schema_version, created_at)
「镜头表」无独立实体：一场戏的当前分镜 = storyboard 中该 scene_id 的全部行，
因此 storyboard_id 即 scene_id（POST 重转分镜 = 整场替换，人工编辑走 PUT）。
场次/角色 id 沿用 screenplay 的整数 rowid（其 0001 迁移已注明与本模块对齐），
幂等 DDL（CREATE … IF NOT EXISTS）同为两模块共库约定，不碰 user_version。

上游集成（剧本数据经 screenplay 的读函数，task 2.1/2.2 交付）：
load_scene_bundle 用 screenplay.connect/_project_tree 组装
场次（title/synopsis）+ 台词（idx/speaker_name/text）+ 角色要素集（appearance dict）。
并行开发期 screenplay 未落地时返回 503；测试/联调可替换 load_scene_bundle 接缝。
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from . import llm

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])

# ---------------------------------------------------------------- 常量

SHOT_SIZES = ["全景", "中景", "近景", "特写"]
CAMERA_MOVES = ["固定机位", "缓慢跟拍", "手持轻晃", "正反打"]
STYLE_ANCHOR = "电影感写实画风，柔和自然光影，35mm 胶片质感，构图克制"
PROMPT_SCHEMA_VERSION = "1"
PROMPT_FORMS = ("image", "video", "narrative")
# 中文台词语速约 3 字/秒；定场/收尾镜的默认时长（秒）
CHARS_PER_SEC = 3
ESTABLISH_SEC = 4
ENDING_SEC = 3


# ---------------------------------------------------------------- 存储（共库自建表）


def _db_path() -> str:
    return os.environ.get("FD_JUCHUANG_DB", "juchuang.db")


def connect() -> sqlite3.Connection:
    path = _db_path()
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS storyboard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scene_id INTEGER NOT NULL,
            idx INTEGER NOT NULL,
            shot TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (scene_id, idx)
        );
        CREATE TABLE IF NOT EXISTS promptset (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            storyboard_id INTEGER NOT NULL,
            form TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (storyboard_id, form)
        );
        """
    )
    conn.commit()


def _row_shot(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "scene_id": row["scene_id"], "idx": row["idx"],
            "shot": json.loads(row["shot"]), "created_at": row["created_at"]}


def _load_storyboard(conn: sqlite3.Connection, storyboard_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM storyboard WHERE scene_id = ? ORDER BY idx", (storyboard_id,)
    ).fetchall()
    return [_row_shot(r) for r in rows]


# ---------------------------------------------------------------- 上游剧本读取（接缝）


def _norm_elements(raw: Any) -> list[str]:
    """要素集归一为字符串列表，保留原文（角色一致性的注入单位）。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, dict):
        return [f"{k}：{v}" for k, v in raw.items()]
    if isinstance(raw, (list, tuple)):
        out: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                out.extend(f"{k}：{v}" for k, v in item.items())
            else:
                out.append(str(item))
        return out
    return [str(raw)]


def _pick(mapping: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _normalize_bundle(bundle: Any, scene_id: int) -> dict:
    """容忍少量键名别名的归一化（id 一律字符串，沿用 screenplay 的 uuid hex）。"""
    scene = _pick(bundle, "scene", default={}) or {}
    lines_raw = _pick(bundle, "lines", "dialogues", "speeches", default=[]) or []
    chars_raw = _pick(bundle, "characters", "cast", "roles", default=[]) or []

    lines = []
    for pos, item in enumerate(lines_raw):
        text = _pick(item, "text", "content", "line", "line_text", default="")
        speaker = _pick(item, "speaker", "speaker_name", "character",
                        "character_name", "name", default="")
        idx = _pick(item, "idx", "order", "sequence", default=pos + 1)
        if str(text).strip():
            lines.append({"idx": int(idx), "speaker": str(speaker).strip(),
                          "text": str(text).strip()})

    characters = []
    for item in chars_raw:
        cid = _pick(item, "id", "character_id")
        name = _pick(item, "name", "character_name", default="")
        if cid is None or not str(name).strip():
            continue
        characters.append({
            "id": int(cid),
            "name": str(name).strip(),
            "appearance_elements": _norm_elements(
                _pick(item, "appearance_elements", "appearance", "elements",
                      "elements_set", "style_elements")),
        })

    return {
        "scene": {
            "id": int(_pick(scene, "id", default=scene_id)),
            "heading": str(_pick(scene, "heading", "scene_heading", "title",
                                 "name", default=f"场次 {scene_id}")),
            "synopsis": str(_pick(scene, "synopsis", "summary", "description",
                                  default="")),
        },
        "lines": lines,
        "characters": characters,
    }


def load_scene_bundle(scene_id: int) -> dict:
    """经 screenplay 读函数取场次/台词/角色要素集（task 2.1/2.2 交付）。

    用 screenplay.connect()（共库连接）+ _project_tree（剧本树读取函数）
    组装本场 bundle；场次不存在 → 404；screenplay 未落地 → 503。
    测试与联调可直接替换本函数（模块级接缝，端点在请求时才解析名字）。
    """
    try:
        from . import screenplay
    except ImportError as exc:  # 并行开发期：上游模块尚未落地
        raise HTTPException(
            status_code=503,
            detail=f"剧本模块（screenplay）未就绪，无法读取场次 {scene_id}: {exc}",
        ) from exc
    conn = screenplay.connect()
    try:
        screenplay.migrate(conn)
        row = conn.execute(
            "SELECT id, project_id FROM scenes WHERE id = ?", (scene_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"场次 {scene_id} 不存在")
        tree = screenplay._project_tree(conn, row["project_id"])  # noqa: SLF001 —— screenplay 的剧本树读取函数（集成点）
    finally:
        conn.close()
    for scene in tree.get("scenes", []):
        if scene.get("id") == scene_id:
            return _normalize_bundle({
                "scene": scene,
                "lines": scene.get("lines", []),
                "characters": tree.get("characters", []),
            }, scene_id)
    raise HTTPException(status_code=404, detail=f"场次 {scene_id} 不存在")


# ---------------------------------------------------------------- 4.1 剧本 → 分镜（确定性 + LLM 润色）


def _deterministic_shots(bundle: dict) -> list[dict]:
    scene = bundle["scene"]
    heading, synopsis = scene["heading"], scene["synopsis"]
    setting = f"{heading}；{synopsis}" if synopsis else heading

    shots: list[dict] = [{
        "idx": 0,
        "shot_size": "全景",
        "visual": f"{setting}（定场）",
        "action": "镜头缓推，交代环境与人物站位",
        "line_text": None,
        "line_speaker": None,
        "duration_sec": ESTABLISH_SEC,
        "engine": "deterministic",
    }]
    for pos, line in enumerate(bundle["lines"], start=1):
        text, speaker = line["text"], line["speaker"]
        size = SHOT_SIZES[len(text) % 4]  # 按句长轮换景别
        excerpt = text[:16] + "…" if len(text) > 16 else text
        shots.append({
            "idx": pos,
            "shot_size": size,
            "visual": f"{setting}；{speaker or '旁白'}（{size}）：{excerpt}",
            "action": f"{speaker or '旁白'}开口，神情与手势随语义起伏" if speaker
                      else "画面随旁白语流缓缓推移",
            "line_text": text,
            "line_speaker": speaker or None,
            "duration_sec": max(2, math.ceil(len(text) / CHARS_PER_SEC)),
            "engine": "deterministic",
        })
    shots.append({
        "idx": len(shots),
        "shot_size": "全景",
        "visual": f"{setting}，对话落定，全场归于静默（收尾）",
        "action": "镜头缓缓拉远，收束全场",
        "line_text": None,
        "line_speaker": None,
        "duration_sec": ENDING_SEC,
        "engine": "deterministic",
    })
    return shots


def _loads_lenient(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):  # 剥掉 markdown 代码围栏
        text = text.strip("`").strip()
        if "\n" in text:
            text = text.split("\n", 1)[1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _polish_with_llm(shots: list[dict], bundle: dict) -> list[dict]:
    """LLM 仅润色 visual/action（一次性整场调用）；任何失败抛 LLMError 由调用方降级。"""
    scene = bundle["scene"]
    material = [
        {"idx": s["idx"], "shot_size": s["shot_size"], "visual": s["visual"],
         "action": s["action"], "line_speaker": s["line_speaker"],
         "line_text": s["line_text"]}
        for s in shots
    ]
    system = (
        "你是电影分镜师。对给定镜头表逐镜润色画面描述(visual)与动作(action)，"
        "使其更具镜头感与可视性；不得改变景别、台词、时长与镜头归属。"
        '只输出 JSON 数组：[{"idx": int, "visual": str, "action": str}, ...]，不要多余文字。'
    )
    content = llm.chat(
        [{"role": "system", "content": system},
         {"role": "user", "content": json.dumps(
             {"scene": scene, "shots": material}, ensure_ascii=False)}],
        temperature=0.4,
        max_tokens=1600,
    )
    if not content:
        raise llm.LLMError("LLM 网关返回空响应")
    try:
        data = _loads_lenient(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise llm.LLMError(f"LLM 润色负载不是合法 JSON: {exc}") from exc
    if not isinstance(data, list):
        raise llm.LLMError("LLM 润色负载不是 JSON 数组")
    by_idx = {s["idx"]: dict(s) for s in shots}
    known = set(by_idx)
    for item in data:
        if not isinstance(item, dict) or "idx" not in item:
            continue
        idx = item["idx"]
        if not isinstance(idx, int) or idx not in known:
            continue
        for key in ("visual", "action"):
            value = item.get(key)
            if isinstance(value, str) and value.strip() and len(value) <= 2000:
                by_idx[idx][key] = value.strip()
    return [by_idx[s["idx"]] for s in shots]


def build_storyboard(bundle: dict) -> tuple[list[dict], str]:
    """确定性版必做；.llm 有 KEY 时尝试 LLM 润色，超时/失败回退并标 engine。"""
    shots = _deterministic_shots(bundle)
    engine = "deterministic"
    if llm.is_configured():
        try:
            shots = _polish_with_llm(shots, bundle)
            engine = "llm"
        except llm.LLMError:
            shots = _deterministic_shots(bundle)
            engine = "deterministic"
    for shot in shots:
        shot["engine"] = engine
    return shots, engine


class ShotPatch(BaseModel):
    """逐镜人工编辑（人在环上）：至少改一格，景别限定四档。"""
    model_config = ConfigDict(extra="forbid")

    shot_size: str | None = Field(default=None, pattern="^(全景|中景|近景|特写)$")
    visual: str | None = Field(default=None, min_length=1, max_length=2000)
    action: str | None = Field(default=None, min_length=1, max_length=2000)
    line_text: str | None = Field(default=None, max_length=2000)
    line_speaker: str | None = Field(default=None, max_length=200)
    duration_sec: float | None = Field(default=None, gt=0, le=600)


@router.post("/storyboard/{scene_id}")
def create_storyboard(scene_id: int) -> dict:
    """场次 → 镜头表（重转 = 整场替换；产出后逐镜 PUT 编辑）。"""
    bundle = load_scene_bundle(scene_id)
    shots, engine = build_storyboard(bundle)
    conn = connect()
    try:
        with conn:
            conn.execute("DELETE FROM storyboard WHERE scene_id = ?", (scene_id,))
            conn.executemany(
                "INSERT INTO storyboard (scene_id, idx, shot) VALUES (?, ?, ?)",
                [(scene_id, s["idx"], json.dumps(s, ensure_ascii=False)) for s in shots],
            )
        rows = _load_storyboard(conn, scene_id)
    finally:
        conn.close()
    return {
        "scene_id": scene_id,
        "storyboard_id": scene_id,
        "engine": engine,
        "shot_count": len(rows),
        "shots": [r["shot"] for r in rows],
    }


@router.get("/storyboard/{storyboard_id}")
def get_storyboard(storyboard_id: int) -> dict:
    conn = connect()
    try:
        rows = _load_storyboard(conn, storyboard_id)
    finally:
        conn.close()
    if not rows:
        raise HTTPException(status_code=404,
                            detail=f"场次 {storyboard_id} 尚无镜头表，先 POST 转分镜")
    return {"scene_id": storyboard_id, "storyboard_id": storyboard_id,
            "shot_count": len(rows), "shots": [r["shot"] for r in rows]}


@router.put("/storyboard/{storyboard_id}/{idx}")
def update_shot(storyboard_id: int, idx: int, patch: ShotPatch) -> dict:
    """逐镜编辑一格（merge 语义：只覆盖提交的字段）。"""
    fields = patch.model_dump(exclude_unset=True, exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="至少提交一个要编辑的字段")
    if "duration_sec" in fields:
        fields["duration_sec"] = int(fields["duration_sec"]) if float(
            fields["duration_sec"]).is_integer() else fields["duration_sec"]
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM storyboard WHERE scene_id = ? AND idx = ?",
            (storyboard_id, idx),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"镜头表 {storyboard_id} 不存在 idx={idx} 的镜头",
            )
        shot = json.loads(row["shot"])
        shot.update(fields)
        shot["idx"] = idx  # 镜头序号不可经编辑漂移
        with conn:
            conn.execute(
                "UPDATE storyboard SET shot = ? WHERE id = ?",
                (json.dumps(shot, ensure_ascii=False), row["id"]),
            )
        updated = conn.execute("SELECT * FROM storyboard WHERE id = ?",
                               (row["id"],)).fetchone()
        return _row_shot(updated)
    finally:
        conn.close()


# ---------------------------------------------------------------- 4.2/4.3 分镜 → 三形态提示词


def _characters_by_name(bundle: dict) -> dict[str, dict]:
    return {c["name"]: c for c in bundle["characters"]}


def _shot_character(shot: dict, chars: dict[str, dict]) -> dict | None:
    """镜头归属角色：按台词说话人对名（含要素集的角色卡即一致性锚点）。"""
    speaker = (shot.get("line_speaker") or "").strip()
    return chars.get(speaker) if speaker else None


def _element_text(elements: list[str]) -> str:
    return "；".join(elements)


def _build_image_payload(storyboard_id: int, bundle: dict, shots: list[dict]) -> dict:
    chars = _characters_by_name(bundle)
    out = []
    for shot in shots:
        char = _shot_character(shot, chars)
        prompt = f"{STYLE_ANCHOR}｜{shot['visual']}"
        if char:
            # 角色一致性（spec）：要素集原文注入 + character_id 字段
            prompt += (f"｜人物锁定——{char['name']}"
                       f"：{_element_text(char['appearance_elements'])}")
        out.append({
            "idx": shot["idx"],
            "shot_size": shot["shot_size"],
            "prompt": prompt,
            "character_id": char["id"] if char else None,
            "character_name": char["name"] if char else None,
            "character_elements": list(char["appearance_elements"]) if char else [],
        })
    return {
        "form": "image",
        "schema_version": PROMPT_SCHEMA_VERSION,
        "storyboard_id": storyboard_id,
        "scene": bundle["scene"],
        "style_anchor": STYLE_ANCHOR,
        "shots": out,
    }


def _build_video_payload(storyboard_id: int, bundle: dict, shots: list[dict]) -> dict:
    chars = _characters_by_name(bundle)
    out = []
    for shot in shots:
        char = _shot_character(shot, chars)
        if shot["idx"] == 0:
            move = "缓推定场"
        elif shot["idx"] == len(shots) - 1:
            move = "缓慢拉远"
        else:
            move = CAMERA_MOVES[shot["idx"] % len(CAMERA_MOVES)]
        desc = f"{shot['visual']}；{shot['action']}"
        if char:
            desc += (f"；人物锁定——{char['name']}"
                     f"：{_element_text(char['appearance_elements'])}")
        out.append({
            "idx": shot["idx"],
            "shot": desc,
            "duration_sec": shot["duration_sec"],
            "camera_move": move,
            "character_id": char["id"] if char else None,
            "character_name": char["name"] if char else None,
            "character_elements": list(char["appearance_elements"]) if char else [],
        })
    return {
        "form": "video",
        "schema_version": PROMPT_SCHEMA_VERSION,
        "storyboard_id": storyboard_id,
        "scene": bundle["scene"],
        "shots": out,
    }


def _build_narrative_payload(storyboard_id: int, bundle: dict) -> dict:
    scene = bundle["scene"]
    parts: list[str] = [f"{scene['heading']}。"]
    if scene["synopsis"]:
        parts.append(f"{scene['synopsis']}。")
    for line in bundle["lines"]:
        speaker = f"{line['speaker']}道" if line["speaker"] else "旁白起"
        parts.append(f"{speaker}：「{line['text']}」")
    parts.append("本场收束。")
    text = "".join(parts)
    return {
        "form": "narrative",
        "schema_version": PROMPT_SCHEMA_VERSION,
        "storyboard_id": storyboard_id,
        "scene": scene,
        "text": text,
        "word_count": len(text),
    }


def _build_payloads(storyboard_id: int, bundle: dict, shots: list[dict]) -> dict[str, dict]:
    return {
        "image": _build_image_payload(storyboard_id, bundle, shots),
        "video": _build_video_payload(storyboard_id, bundle, shots),
        "narrative": _build_narrative_payload(storyboard_id, bundle),
    }


@router.post("/prompts/{storyboard_id}")
def create_promptsets(storyboard_id: int) -> dict:
    """镜头表 → 三形态提示词（重导出 = 替换该镜头表旧 promptset）。"""
    conn = connect()
    try:
        rows = _load_storyboard(conn, storyboard_id)
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"镜头表 {storyboard_id} 不存在，先 POST /pipeline/storyboard/{storyboard_id}",
            )
        bundle = load_scene_bundle(storyboard_id)
        payloads = _build_payloads(storyboard_id, bundle, [r["shot"] for r in rows])
        with conn:
            conn.execute("DELETE FROM promptset WHERE storyboard_id = ?",
                         (storyboard_id,))
            for form in PROMPT_FORMS:
                conn.execute(
                    "INSERT INTO promptset (storyboard_id, form, payload, schema_version)"
                    " VALUES (?, ?, ?, ?)",
                    (storyboard_id, form,
                     json.dumps(payloads[form], ensure_ascii=False),
                     PROMPT_SCHEMA_VERSION),
                )
        created = conn.execute(
            "SELECT id, form, created_at FROM promptset WHERE storyboard_id = ?"
            " ORDER BY form", (storyboard_id,)
        ).fetchall()
    finally:
        conn.close()
    return {
        "storyboard_id": storyboard_id,
        "schema_version": PROMPT_SCHEMA_VERSION,
        "promptsets": [{"id": r["id"], "form": r["form"],
                        "created_at": r["created_at"]} for r in created],
    }


def _get_promptset_row(conn: sqlite3.Connection, promptset_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM promptset WHERE id = ?",
                       (promptset_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"提示词集 {promptset_id} 不存在")
    return row


@router.get("/prompts/{promptset_id}")
def get_promptset(promptset_id: int) -> dict:
    """按形态查询：一个 promptset 即一种形态（form 字段）。"""
    conn = connect()
    try:
        row = _get_promptset_row(conn, promptset_id)
    finally:
        conn.close()
    return {
        "id": row["id"],
        "storyboard_id": row["storyboard_id"],
        "form": row["form"],
        "schema_version": row["schema_version"],
        "payload": json.loads(row["payload"]),
        "created_at": row["created_at"],
    }


@router.get("/prompts/{promptset_id}/export")
def export_promptset(
    promptset_id: int,
    form: str | None = Query(default=None, pattern="^(image|video|narrative)$"),
) -> Response:
    """纯 JSON 下载体（payload 本体，Content-Disposition 附件）。"""
    conn = connect()
    try:
        row = _get_promptset_row(conn, promptset_id)
    finally:
        conn.close()
    if form is not None and form != row["form"]:
        raise HTTPException(
            status_code=409,
            detail=f"提示词集 {promptset_id} 是 {row['form']} 形态，与请求的 {form} 不符",
        )
    filename = f"promptset-{promptset_id}-{row['form']}.json"
    return Response(
        content=row["payload"],
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
