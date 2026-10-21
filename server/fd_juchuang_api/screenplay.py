"""结构化剧本工作台（task 2.1/2.2/2.3）：项目→版本→场次→台词 + 角色卡。

数据模型（spec「结构化剧本创作」）：
- projects / characters / scenes / lines / versions，全部 SQLite 承载
  （env FD_JUCHUANG_DB，默认 ~/.fd-juchuang/juchuang.db；DDL 幂等可重放，
  与 personal/pipeline 共库——user_version 计数器归 personal，本模块不碰）。
- 主键为 SQLite rowid 整数（与 pipeline 模块的 storyboard.scene_id INTEGER、
  int 路由参数对齐——task 4.x 的集成契约）。
- 版本快照 = 全量剧本树（项目+角色+场次+台词）JSON，回滚 = 快照重放 + 新版本留痕。
- 对手戏张力：场次 conflict {positions:[a,b], source}；两角色 stance 存在时
  tension-check 给本地文本差异版轴差（真轴差由哲思契约模块做，见 task 3.2）。

鉴权：require_user（auth.py）。auth 依赖的 personal 底座若尚未交付（并行开发期），
import 会失败——这里兜底一个同语义的 dev-token 校验，personal 落地后自动切真实现。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---- 鉴权接线（见模块 docstring） ----

try:  # 正式路径：auth.py 的 require_user（含审计留痕）
    from .auth import require_user
except Exception:  # noqa: BLE001 —— personal 底座未交付时的降级兜底，交付后本分支不触发
    def require_user(request: Request) -> str:  # type: ignore[misc]
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if token:
            for var in ("FD_JUCHUANG_AUTH_DEV_TOKENS", "FD__AUTH_DEV_TOKENS"):
                for pair in os.environ.get(var, "").split(","):
                    if "=" in pair and pair.split("=", 1)[0].strip() == token:
                        return pair.split("=", 1)[1].strip()
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")


# ---- 存储 ----

MIGRATIONS = [
    # 0001：剧本五表（rowid 整数主键，pipeline 的 scene_id 外键同为整数）。
    # 共库多模块：user_version 计数器由 personal 模块持有（其 migrate 独占使用），
    # 本模块按 pipeline 同款约定用幂等 DDL（CREATE … IF NOT EXISTS），不碰计数器——
    # 否则两模块的迁移链会在同一 DB 文件上互相「吃掉」对方的版本号。
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        logline TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id, created_at);
    CREATE TABLE IF NOT EXISTS characters (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        appearance TEXT NOT NULL,                  -- JSON 要素集：年龄感/体型/着装/画风标签…
        stance TEXT,                               -- JSON {position, reasons?, source?}
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_characters_project ON characters(project_id, created_at);
    CREATE TABLE IF NOT EXISTS scenes (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        idx INTEGER NOT NULL,                      -- 场次序号，自动连续编号
        title TEXT NOT NULL,
        synopsis TEXT,
        conflict TEXT,                             -- JSON {positions:[a,b], source?}
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_scenes_project ON scenes(project_id, idx);
    CREATE TABLE IF NOT EXISTS lines (
        id INTEGER PRIMARY KEY,
        scene_id INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
        idx INTEGER NOT NULL,                      -- 台词序号，自动连续编号
        speaker_id INTEGER NOT NULL REFERENCES characters(id),
        text TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_lines_scene ON lines(scene_id, idx);
    CREATE TABLE IF NOT EXISTS versions (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        snapshot TEXT NOT NULL,                    -- 完整剧本树 JSON
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_versions_project ON versions(project_id, created_at);
    """,
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or os.environ.get("FD_JUCHUANG_DB", "")
    if not path:
        path = str(Path.home() / ".fd-juchuang" / "juchuang.db")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """幂等执行全部迁移脚本（DDL 自带 IF NOT EXISTS，可无限重放；不碰 user_version）。"""
    for ddl in MIGRATIONS:
        conn.executescript(ddl)
    conn.commit()
    return len(MIGRATIONS)


def _db() -> sqlite3.Connection:
    conn = connect()
    migrate(conn)
    return conn


def _loads(raw: str | None) -> Any:
    return json.loads(raw) if raw else None


def _dumps(value: Any) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value is not None else None


# ---- 校验模型（422 语义） ----


class ConflictModel(BaseModel):
    """场次张力标注：双方立场 + 张力来源（可溯到哲思张力卡）。"""

    model_config = ConfigDict(extra="forbid")
    positions: tuple[str, str] = Field(min_length=2, max_length=2)
    source: str | None = None

    @model_validator(mode="after")
    def _nonempty(self) -> "ConflictModel":
        if not self.positions[0].strip() or not self.positions[1].strip():
            raise ValueError("conflict.positions 双方立场均须非空")
        return self


class StanceModel(BaseModel):
    """角色立场卡：position 必填；reasons/source 可空（source 指向哲思立场卡）。"""

    model_config = ConfigDict(extra="forbid")
    position: str = Field(min_length=1)
    reasons: str | None = None
    source: str | None = None


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    logline: str | None = None


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    logline: str | None = None


def _normalize_appearance(raw: dict[str, str]) -> dict[str, str]:
    """要素集归一：剔空键空值；不足 2 个非空键 → 422。"""
    valid = {
        k.strip(): v.strip()
        for k, v in raw.items()
        if k.strip() and v and v.strip()
    }
    if len(valid) < 2:
        raise ValueError(
            "appearance 至少 2 个非空键（外观/风格要素集，如年龄感/体型/着装/画风标签）"
        )
    return valid


class CharacterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    appearance: dict[str, str]
    stance: StanceModel | None = None

    @model_validator(mode="after")
    def _appearance_at_least_two(self) -> "CharacterIn":
        self.appearance = _normalize_appearance(self.appearance)
        return self


class CharacterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    appearance: dict[str, str] | None = None
    stance: StanceModel | None = None

    @model_validator(mode="after")
    def _appearance_if_given(self) -> "CharacterPatch":
        if self.appearance is not None:
            self.appearance = _normalize_appearance(self.appearance)
        return self


class SceneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    synopsis: str | None = None
    conflict: ConflictModel | None = None


class ScenePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    synopsis: str | None = None
    conflict: ConflictModel | None = None
    idx: int | None = Field(default=None, ge=1)


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speaker_id: int
    text: str = Field(min_length=1)


class LinePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speaker_id: int | None = None
    text: str | None = None
    idx: int | None = Field(default=None, ge=1)


# ---- 行转换 ----


def _project_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "title": r["title"], "logline": r["logline"],
            "created_at": r["created_at"]}


def _character_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "project_id": r["project_id"], "name": r["name"],
            "appearance": _loads(r["appearance"]), "stance": _loads(r["stance"]),
            "created_at": r["created_at"]}


def _scene_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "project_id": r["project_id"], "idx": r["idx"],
            "title": r["title"], "synopsis": r["synopsis"],
            "conflict": _loads(r["conflict"]), "created_at": r["created_at"]}


def _line_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "scene_id": r["scene_id"], "idx": r["idx"],
            "speaker_id": r["speaker_id"], "text": r["text"]}


def _version_dict(r: sqlite3.Row, with_snapshot: bool = False) -> dict:
    snap = _loads(r["snapshot"])
    out: dict = {"id": r["id"], "project_id": r["project_id"],
                 "created_at": r["created_at"],
                 "action": (snap.get("meta") or {}).get("action", "save"),
                 "restored_from": (snap.get("meta") or {}).get("restored_from")}
    if with_snapshot:
        out["snapshot"] = snap
    return out


# ---- 内部工具 ----


def _owned_project(conn: sqlite3.Connection, user_id: str, pid: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM projects WHERE id=? AND user_id=?", (pid, user_id)
    ).fetchone()


def _need_project(conn: sqlite3.Connection, user_id: str, pid: int) -> sqlite3.Row:
    row = _owned_project(conn, user_id, pid)
    if not row:
        raise HTTPException(status_code=404, detail="项目不存在")
    return row


def _need_scene(conn: sqlite3.Connection, user_id: str, sid: int,
                ) -> tuple[sqlite3.Row, sqlite3.Row]:
    """返回 (scene_row, project_row)；归属校验经 join projects。"""
    row = conn.execute(
        "SELECT s.* FROM scenes s JOIN projects p ON s.project_id=p.id"
        " WHERE s.id=? AND p.user_id=?",
        (sid, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="场次不存在")
    proj = conn.execute("SELECT * FROM projects WHERE id=?", (row["project_id"],)).fetchone()
    return row, proj


def _project_tree(conn: sqlite3.Connection, pid: int) -> dict:
    """完整剧本树（export 与版本快照共用）。"""
    proj = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    characters = [_character_dict(r) for r in conn.execute(
        "SELECT * FROM characters WHERE project_id=? ORDER BY id", (pid,)
    ).fetchall()]
    name_of = {c["id"]: c["name"] for c in characters}
    scenes = []
    for sr in conn.execute(
        "SELECT * FROM scenes WHERE project_id=? ORDER BY idx", (pid,)
    ).fetchall():
        scene = _scene_dict(sr)
        scene["lines"] = [
            {**_line_dict(lr), "speaker_name": name_of.get(lr["speaker_id"])}
            for lr in conn.execute(
                "SELECT * FROM lines WHERE scene_id=? ORDER BY idx", (sr["id"],)
            ).fetchall()
        ]
        scenes.append(scene)
    return {"project": _project_dict(proj), "characters": characters, "scenes": scenes}


def _snapshot(conn: sqlite3.Connection, pid: int, action: str,
              restored_from: int | None = None) -> dict:
    tree = _project_tree(conn, pid)
    tree["meta"] = {"action": action, "restored_from": restored_from}
    return tree


def _reorder(conn: sqlite3.Connection, table: str, scope_col: str, scope_val: int,
             item_id: int, target: int) -> None:
    """把 item_id 移到第 target 位并整体重排（纯列表法，避免 idx 并列歧义）。"""
    ids = [r["id"] for r in conn.execute(
        f"SELECT id FROM {table} WHERE {scope_col}=? ORDER BY idx", (scope_val,)
    ).fetchall()]
    ids.remove(item_id)
    target = max(1, min(target, len(ids) + 1))
    ids.insert(target - 1, item_id)
    for i, iid in enumerate(ids, start=1):
        conn.execute(f"UPDATE {table} SET idx=? WHERE id=?", (i, iid))


def _renumber_scenes(conn: sqlite3.Connection, pid: int) -> None:
    for i, r in enumerate(
        conn.execute("SELECT id FROM scenes WHERE project_id=? ORDER BY idx", (pid,)).fetchall(),
        start=1,
    ):
        conn.execute("UPDATE scenes SET idx=? WHERE id=?", (i, r["id"]))


def _renumber_lines(conn: sqlite3.Connection, sid: int) -> None:
    for i, r in enumerate(
        conn.execute("SELECT id FROM lines WHERE scene_id=? ORDER BY idx", (sid,)).fetchall(),
        start=1,
    ):
        conn.execute("UPDATE lines SET idx=? WHERE id=?", (i, r["id"]))


def _max_idx(conn: sqlite3.Connection, table: str, col: str, val: int) -> int:
    row = conn.execute(
        f"SELECT COALESCE(MAX(idx), 0) FROM {table} WHERE {col}=?", (val,)
    ).fetchone()
    return int(row[0])


# ---- 路由 ----

router = APIRouter(prefix="/api/v1/screenplay", tags=["screenplay"])


# ==== 项目 ====


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO projects (id, user_id, title, logline, created_at)"
            " VALUES (NULL,?,?,?,?)",
            (user_id, body.title.strip(), body.logline, now()),
        )
        pid = int(cur.lastrowid)
        conn.commit()
        return _project_dict(conn.execute(
            "SELECT * FROM projects WHERE id=?", (pid,)
        ).fetchone())
    finally:
        conn.close()


@router.get("/projects")
def list_projects(user_id: str = Depends(require_user)) -> list[dict]:
    conn = _db()
    try:
        return [_project_dict(r) for r in conn.execute(
            "SELECT * FROM projects WHERE user_id=? ORDER BY created_at, id", (user_id,)
        ).fetchall()]
    finally:
        conn.close()


@router.get("/projects/{pid}")
def get_project(pid: int, user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        return _project_dict(_need_project(conn, user_id, pid))
    finally:
        conn.close()


@router.patch("/projects/{pid}")
def patch_project(pid: int, body: ProjectPatch,
                  user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        _need_project(conn, user_id, pid)
        sets, vals = [], []
        if "title" in body.model_fields_set and body.title is not None:
            sets.append("title=?")
            vals.append(body.title.strip())
        if "logline" in body.model_fields_set:
            sets.append("logline=?")
            vals.append(body.logline)
        if sets:
            vals.append(pid)
            conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", vals)
            conn.commit()
        return _project_dict(conn.execute(
            "SELECT * FROM projects WHERE id=?", (pid,)
        ).fetchone())
    finally:
        conn.close()


@router.delete("/projects/{pid}", status_code=204)
def delete_project(pid: int, user_id: str = Depends(require_user)) -> None:
    conn = _db()
    try:
        _need_project(conn, user_id, pid)
        conn.execute("DELETE FROM projects WHERE id=?", (pid,))
        conn.commit()
    finally:
        conn.close()


# ==== 角色（task 2.2 角色卡） ====


def _need_character(conn: sqlite3.Connection, user_id: str, pid: int,
                    cid: int) -> sqlite3.Row:
    _need_project(conn, user_id, pid)
    row = conn.execute(
        "SELECT * FROM characters WHERE id=? AND project_id=?", (cid, pid)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="角色不存在")
    return row


@router.post("/projects/{pid}/characters", status_code=201)
def create_character(pid: int, body: CharacterIn,
                     user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        _need_project(conn, user_id, pid)
        cur = conn.execute(
            "INSERT INTO characters (id, project_id, name, appearance, stance, created_at)"
            " VALUES (NULL,?,?,?,?,?)",
            (pid, body.name.strip(), _dumps(body.appearance),
             _dumps(body.stance.model_dump() if body.stance else None), now()),
        )
        cid = int(cur.lastrowid)
        conn.commit()
        return _character_dict(conn.execute(
            "SELECT * FROM characters WHERE id=?", (cid,)
        ).fetchone())
    finally:
        conn.close()


@router.get("/projects/{pid}/characters")
def list_characters(pid: int, user_id: str = Depends(require_user)) -> list[dict]:
    conn = _db()
    try:
        _need_project(conn, user_id, pid)
        return [_character_dict(r) for r in conn.execute(
            "SELECT * FROM characters WHERE project_id=? ORDER BY id", (pid,)
        ).fetchall()]
    finally:
        conn.close()


@router.get("/projects/{pid}/characters/{cid}")
def get_character(pid: int, cid: int, user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        return _character_dict(_need_character(conn, user_id, pid, cid))
    finally:
        conn.close()


@router.patch("/projects/{pid}/characters/{cid}")
def patch_character(pid: int, cid: int, body: CharacterPatch,
                    user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        _need_character(conn, user_id, pid, cid)
        sets, vals = [], []
        if "name" in body.model_fields_set and body.name is not None:
            sets.append("name=?")
            vals.append(body.name.strip())
        if "appearance" in body.model_fields_set and body.appearance is not None:
            sets.append("appearance=?")
            vals.append(_dumps(body.appearance))
        if "stance" in body.model_fields_set:
            sets.append("stance=?")
            vals.append(_dumps(body.stance.model_dump() if body.stance else None))
        if sets:
            vals.append(cid)
            conn.execute(f"UPDATE characters SET {', '.join(sets)} WHERE id=?", vals)
            conn.commit()
        return _character_dict(conn.execute(
            "SELECT * FROM characters WHERE id=?", (cid,)
        ).fetchone())
    finally:
        conn.close()


@router.delete("/projects/{pid}/characters/{cid}", status_code=204)
def delete_character(pid: int, cid: int, user_id: str = Depends(require_user)) -> None:
    conn = _db()
    try:
        _need_character(conn, user_id, pid, cid)
        used = conn.execute(
            "SELECT COUNT(*) FROM lines l JOIN scenes s ON l.scene_id=s.id"
            " WHERE l.speaker_id=? AND s.project_id=?", (cid, pid)
        ).fetchone()[0]
        if used:
            raise HTTPException(
                status_code=409,
                detail=f"角色仍被 {used} 句台词引用，先改删相关台词",
            )
        conn.execute("DELETE FROM characters WHERE id=?", (cid,))
        conn.commit()
    finally:
        conn.close()


# ==== 场次 ====


def _need_scene_in_project(conn: sqlite3.Connection, user_id: str, pid: int,
                           sid: int) -> sqlite3.Row:
    _need_project(conn, user_id, pid)
    row = conn.execute(
        "SELECT * FROM scenes WHERE id=? AND project_id=?", (sid, pid)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="场次不存在")
    return row


@router.post("/projects/{pid}/scenes", status_code=201)
def create_scene(pid: int, body: SceneIn, user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        _need_project(conn, user_id, pid)
        idx = _max_idx(conn, "scenes", "project_id", pid) + 1
        cur = conn.execute(
            "INSERT INTO scenes (id, project_id, idx, title, synopsis, conflict, created_at)"
            " VALUES (NULL,?,?,?,?,?,?)",
            (pid, idx, body.title.strip(), body.synopsis,
             _dumps(body.conflict.model_dump() if body.conflict else None), now()),
        )
        sid = int(cur.lastrowid)
        conn.commit()
        return _scene_dict(conn.execute("SELECT * FROM scenes WHERE id=?", (sid,)).fetchone())
    finally:
        conn.close()


@router.get("/projects/{pid}/scenes")
def list_scenes(pid: int, user_id: str = Depends(require_user)) -> list[dict]:
    conn = _db()
    try:
        _need_project(conn, user_id, pid)
        return [_scene_dict(r) for r in conn.execute(
            "SELECT * FROM scenes WHERE project_id=? ORDER BY idx", (pid,)
        ).fetchall()]
    finally:
        conn.close()


@router.get("/projects/{pid}/scenes/{sid}")
def get_scene(pid: int, sid: int, user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        return _scene_dict(_need_scene_in_project(conn, user_id, pid, sid))
    finally:
        conn.close()


@router.patch("/projects/{pid}/scenes/{sid}")
def patch_scene(pid: int, sid: int, body: ScenePatch,
                user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        _need_scene_in_project(conn, user_id, pid, sid)
        sets, vals = [], []
        if "title" in body.model_fields_set and body.title is not None:
            sets.append("title=?")
            vals.append(body.title.strip())
        if "synopsis" in body.model_fields_set:
            sets.append("synopsis=?")
            vals.append(body.synopsis)
        if "conflict" in body.model_fields_set:
            sets.append("conflict=?")
            vals.append(_dumps(body.conflict.model_dump() if body.conflict else None))
        if sets:
            vals.append(sid)
            conn.execute(f"UPDATE scenes SET {', '.join(sets)} WHERE id=?", vals)
        # 显式 idx：移动到目标位后整体重排（idx 自动排序）
        if body.idx is not None:
            _reorder(conn, "scenes", "project_id", pid, sid, body.idx)
        conn.commit()
        return _scene_dict(conn.execute("SELECT * FROM scenes WHERE id=?", (sid,)).fetchone())
    finally:
        conn.close()


@router.delete("/projects/{pid}/scenes/{sid}", status_code=204)
def delete_scene(pid: int, sid: int, user_id: str = Depends(require_user)) -> None:
    conn = _db()
    try:
        _need_scene_in_project(conn, user_id, pid, sid)
        conn.execute("DELETE FROM scenes WHERE id=?", (sid,))  # lines 级联删除
        _renumber_scenes(conn, pid)
        conn.commit()
    finally:
        conn.close()


# ==== 台词 ====


def _need_line(conn: sqlite3.Connection, sid: int, lid: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM lines WHERE id=? AND scene_id=?", (lid, sid)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="台词不存在")
    return row


def _check_speaker(conn: sqlite3.Connection, pid: int, speaker_id: int) -> None:
    row = conn.execute(
        "SELECT id FROM characters WHERE id=? AND project_id=?", (speaker_id, pid)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=422, detail="speaker_id 不属于该项目")


@router.post("/scenes/{sid}/lines", status_code=201)
def create_line(sid: int, body: LineIn, user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        scene, proj = _need_scene(conn, user_id, sid)
        _check_speaker(conn, proj["id"], body.speaker_id)
        idx = _max_idx(conn, "lines", "scene_id", sid) + 1
        cur = conn.execute(
            "INSERT INTO lines (id, scene_id, idx, speaker_id, text) VALUES (NULL,?,?,?,?)",
            (sid, idx, body.speaker_id, body.text.strip()),
        )
        lid = int(cur.lastrowid)
        conn.commit()
        return _line_dict(conn.execute("SELECT * FROM lines WHERE id=?", (lid,)).fetchone())
    finally:
        conn.close()


@router.get("/scenes/{sid}/lines")
def list_lines(sid: int, user_id: str = Depends(require_user)) -> list[dict]:
    conn = _db()
    try:
        _need_scene(conn, user_id, sid)
        return [_line_dict(r) for r in conn.execute(
            "SELECT * FROM lines WHERE scene_id=? ORDER BY idx", (sid,)
        ).fetchall()]
    finally:
        conn.close()


@router.patch("/scenes/{sid}/lines/{lid}")
def patch_line(sid: int, lid: int, body: LinePatch,
               user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        scene, proj = _need_scene(conn, user_id, sid)
        _need_line(conn, sid, lid)
        if "speaker_id" in body.model_fields_set and body.speaker_id is not None:
            _check_speaker(conn, proj["id"], body.speaker_id)
        sets, vals = [], []
        if "speaker_id" in body.model_fields_set and body.speaker_id is not None:
            sets.append("speaker_id=?")
            vals.append(body.speaker_id)
        if "text" in body.model_fields_set and body.text is not None:
            sets.append("text=?")
            vals.append(body.text.strip())
        if sets:
            vals.append(lid)
            conn.execute(f"UPDATE lines SET {', '.join(sets)} WHERE id=?", vals)
        if body.idx is not None:
            _reorder(conn, "lines", "scene_id", sid, lid, body.idx)
        conn.commit()
        return _line_dict(conn.execute("SELECT * FROM lines WHERE id=?", (lid,)).fetchone())
    finally:
        conn.close()


@router.delete("/scenes/{sid}/lines/{lid}", status_code=204)
def delete_line(sid: int, lid: int, user_id: str = Depends(require_user)) -> None:
    conn = _db()
    try:
        _need_scene(conn, user_id, sid)
        _need_line(conn, sid, lid)
        conn.execute("DELETE FROM lines WHERE id=?", (lid,))
        _renumber_lines(conn, sid)
        conn.commit()
    finally:
        conn.close()


# ==== 版本（快照 / 回滚） ====


@router.post("/projects/{pid}/versions", status_code=201)
def save_version(pid: int, user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        _need_project(conn, user_id, pid)
        snap = _snapshot(conn, pid, "save")
        cur = conn.execute(
            "INSERT INTO versions (id, project_id, snapshot, created_at) VALUES (NULL,?,?,?)",
            (pid, json.dumps(snap, ensure_ascii=False), now()),
        )
        vid = int(cur.lastrowid)
        conn.commit()
        return {"id": vid, "project_id": pid, "created_at": now(), "action": "save"}
    finally:
        conn.close()


@router.get("/projects/{pid}/versions")
def list_versions(pid: int, user_id: str = Depends(require_user)) -> list[dict]:
    conn = _db()
    try:
        _need_project(conn, user_id, pid)
        return [_version_dict(r) for r in conn.execute(
            "SELECT * FROM versions WHERE project_id=? ORDER BY id", (pid,)
        ).fetchall()]
    finally:
        conn.close()


@router.get("/projects/{pid}/versions/{vid}")
def get_version(pid: int, vid: int, user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        _need_project(conn, user_id, pid)
        row = conn.execute(
            "SELECT * FROM versions WHERE id=? AND project_id=?", (vid, pid)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="版本不存在")
        return _version_dict(row, with_snapshot=True)
    finally:
        conn.close()


@router.post("/projects/{pid}/restore/{vid}")
def restore_version(pid: int, vid: int, user_id: str = Depends(require_user)) -> dict:
    """回滚到指定版本：快照重放（原 id 原位）+ 新版本记录回滚动作。"""
    conn = _db()
    try:
        _need_project(conn, user_id, pid)
        row = conn.execute(
            "SELECT * FROM versions WHERE id=? AND project_id=?", (vid, pid)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="版本不存在")
        snap = _loads(row["snapshot"])
        proj = snap["project"]
        characters = snap.get("characters", [])
        scenes = snap.get("scenes", [])
        try:
            conn.execute("BEGIN")
            # 先删场次（级联删台词——台词 FK 引用角色），再删角色，避免 FK 违例
            conn.execute("DELETE FROM scenes WHERE project_id=?", (pid,))
            conn.execute("DELETE FROM characters WHERE project_id=?", (pid,))
            conn.execute(
                "UPDATE projects SET title=?, logline=?, created_at=? WHERE id=?",
                (proj["title"], proj.get("logline"), proj["created_at"], pid),
            )
            for c in characters:
                conn.execute(
                    "INSERT INTO characters (id, project_id, name, appearance, stance,"
                    " created_at) VALUES (?,?,?,?,?,?)",
                    (c["id"], pid, c["name"], _dumps(c["appearance"]),
                     _dumps(c.get("stance")), c["created_at"]),
                )
            for s in scenes:
                conn.execute(
                    "INSERT INTO scenes (id, project_id, idx, title, synopsis, conflict,"
                    " created_at) VALUES (?,?,?,?,?,?,?)",
                    (s["id"], pid, s["idx"], s["title"], s.get("synopsis"),
                     _dumps(s.get("conflict")), s["created_at"]),
                )
                for ln in s.get("lines", []):
                    conn.execute(
                        "INSERT INTO lines (id, scene_id, idx, speaker_id, text)"
                        " VALUES (?,?,?,?,?)",
                        (ln["id"], s["id"], ln["idx"], ln["speaker_id"], ln["text"]),
                    )
            new_snap = _snapshot(conn, pid, "restore", restored_from=vid)
            cur = conn.execute(
                "INSERT INTO versions (id, project_id, snapshot, created_at) VALUES (NULL,?,?,?)",
                (pid, json.dumps(new_snap, ensure_ascii=False), now()),
            )
            new_vid = int(cur.lastrowid)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return {"restored_to": vid, "new_version_id": new_vid,
                "action": "restore", "export": _project_tree(conn, pid)}
    finally:
        conn.close()


# ==== 导出 ====


@router.get("/projects/{pid}/export")
def export_project(pid: int, user_id: str = Depends(require_user)) -> dict:
    """完整结构化剧本 JSON：项目 + 角色 + 场次（含台词树，speaker 名已解析）。"""
    conn = _db()
    try:
        _need_project(conn, user_id, pid)
        return _project_tree(conn, pid)
    finally:
        conn.close()


# ==== 对手戏张力标注（本地版；真轴差由哲思契约模块做，task 3.2） ====


@router.get("/scenes/{sid}/tension-check")
def tension_check(sid: int, user_id: str = Depends(require_user)) -> dict:
    conn = _db()
    try:
        scene, proj = _need_scene(conn, user_id, sid)
        stances: list[dict] = []
        seen: set[int] = set()
        # 优先取本场开口且有立场的角色（对手戏双方）
        for lr in conn.execute(
            "SELECT DISTINCT speaker_id FROM lines WHERE scene_id=? ORDER BY idx", (sid,)
        ).fetchall():
            cr = conn.execute(
                "SELECT * FROM characters WHERE id=?", (lr["speaker_id"],)
            ).fetchone()
            if cr and cr["stance"] and cr["id"] not in seen:
                seen.add(cr["id"])
                stances.append({"character_id": cr["id"], "name": cr["name"],
                                "position": _loads(cr["stance"])["position"]})
        if len(stances) < 2:  # 场上不足两方时退到项目内有立场的角色
            for cr in conn.execute(
                "SELECT * FROM characters WHERE project_id=? ORDER BY id", (proj["id"],)
            ).fetchall():
                if cr["stance"] and cr["id"] not in seen:
                    seen.add(cr["id"])
                    stances.append({"character_id": cr["id"], "name": cr["name"],
                                    "position": _loads(cr["stance"])["position"]})
                    if len(stances) >= 2:
                        break
        axis_diff = None
        if len(stances) >= 2:
            p1, p2 = stances[0]["position"], stances[1]["position"]
            axis_diff = {
                "mode": "local-text-diff",
                "same": p1.strip() == p2.strip(),
                "positions": [p1, p2],
            }
        return {
            "scene_id": sid,
            "scene_title": scene["title"],
            "conflict": _loads(scene["conflict"]),
            "stance_holders": stances[:2],
            "axis_diff": axis_diff,
            "note": "本地文本差异比较（无哲思模式）；真轴差由哲思契约模块提供",
        }
    finally:
        conn.close()


# ---- pipeline 集成契约（task 4.x：剧本 → 分镜的上游读函数） ----


def scene_bundle(scene_id: int) -> dict | None:
    """给 pipeline.load_scene_bundle 的场次束；场次不存在返回 None（其侧转 404）。

    形状（与 pipeline 模块 docstring 契约一致）：
      {"scene": {"id", "heading", "synopsis"},
       "lines": [{"idx", "speaker", "text"}],
       "characters": [{"id", "name", "appearance_elements": [str, ...]}]}
    """
    conn = _db()
    try:
        row = conn.execute("SELECT * FROM scenes WHERE id=?", (scene_id,)).fetchone()
        if not row:
            return None
        name_of = {
            cr["id"]: cr["name"]
            for cr in conn.execute(
                "SELECT id, name FROM characters WHERE project_id=?", (row["project_id"],)
            ).fetchall()
        }
        return {
            "scene": {"id": row["id"], "heading": row["title"],
                      "synopsis": row["synopsis"] or ""},
            "lines": [
                {"idx": lr["idx"], "speaker": name_of.get(lr["speaker_id"], ""),
                 "text": lr["text"]}
                for lr in conn.execute(
                    "SELECT * FROM lines WHERE scene_id=? ORDER BY idx", (scene_id,)
                ).fetchall()
            ],
            "characters": [
                {"id": cr["id"], "name": cr["name"],
                 "appearance_elements": [
                     f"{k}：{v}" for k, v in (_loads(cr["appearance"]) or {}).items()
                 ]}
                for cr in conn.execute(
                    "SELECT * FROM characters WHERE project_id=? ORDER BY id",
                    (row["project_id"],),
                ).fetchall()
            ],
        }
    finally:
        conn.close()
