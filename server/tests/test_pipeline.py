"""AI 底料管线离线测试（task 4.1/4.2/4.3）。

全离线：剧本上游经 pipeline.load_scene_bundle 接缝注入夹具（1 场 6 台词 + 2 角色要素集），
LLM 走 monkeypatch（成功/抛错/坏负载/空响应四态），不打真网关。
覆盖：分镜确定性版字段与切镜规则 → 逐镜 PUT 人在环上编辑 → 三形态提示词
schema 校验（jsonschema 手写 schema + 手写字段断言双保险）→ 角色一致性要素集
原文注入 + character_id → 引擎降级路径 → export 下载体。
"""

from __future__ import annotations

import json
import math

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from fd_juchuang_api import pipeline

try:  # 环境有 jsonschema 则做正式 schema 校验；没有时手写断言仍是硬门槛
    import jsonschema

    HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    HAS_JSONSCHEMA = False

# autouse 夹具替换接缝之前，留存真实适配实现（上游契约测试用）
_REAL_LOAD_SCENE_BUNDLE = pipeline.load_scene_bundle


SCENE_ID = 77  # screenplay 的场次/角色 id 是整数 rowid

LINES = [
    {"idx": 1, "speaker": "沈青梧", "text": "把账拿出来。"},
    {"idx": 2, "speaker": "顾行舟", "text": "什么账，我听不懂你在说什么。"},
    {"idx": 3, "speaker": "沈青梧", "text": "十年前腊月，城南当铺，那一张盖了你私章的借据。"},
    {"idx": 4, "speaker": "顾行舟", "text": "事到如今，你我还分得清谁欠谁吗？"},
    {"idx": 5, "speaker": "沈青梧", "text": "分不清，就让它今夜在此分清。"},
    {"idx": 6, "speaker": "顾行舟", "text": "好，那你听我说完这一段旧事。"},
]
CHARACTERS = [
    {"id": 101, "name": "沈青梧",
     "appearance_elements": ["年龄感：三十五岁上下", "体型：清瘦挺拔",
                             "着装：月白改良旗袍、银襟扣", "画风标签：水墨淡彩、低饱和"]},
    {"id": 102, "name": "顾行舟",
     "appearance_elements": ["年龄感：四十岁上下", "体型：宽肩微驼",
                             "着装：深灰长衫、旧怀表链", "画风标签：油画厚涂、暖褐调"]},
]
BUNDLE = {
    "scene": {"id": SCENE_ID, "heading": "内景·老茶馆·夜",
              "synopsis": "两位旧友为十年前的一笔旧账当面对峙"},
    "lines": LINES,
    "characters": CHARACTERS,
}


def _fake_bundle(scene_id: int) -> dict:
    """镜像真实 load_scene_bundle 契约（归一化后的 bundle 形态）：缺场次 → 404。"""
    if scene_id != SCENE_ID:
        raise HTTPException(status_code=404, detail=f"场次 {scene_id} 不存在")
    return json.loads(json.dumps(BUNDLE, ensure_ascii=False))


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FD_JUCHUANG_DB", str(tmp_path / "pipeline_test.db"))
    monkeypatch.delenv("FD_JUCHUANG_LLM_API_KEY", raising=False)  # 默认确定性引擎
    monkeypatch.setattr(pipeline, "load_scene_bundle", _fake_bundle)


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(pipeline.router)  # 集成到 main.py 的同一行挂载方式
    return TestClient(app)


def _make_storyboard(client: TestClient) -> dict:
    resp = client.post(f"/api/v1/pipeline/storyboard/{SCENE_ID}")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------- 4.1 剧本 → 分镜


def test_storyboard_deterministic(client: TestClient) -> None:
    body = _make_storyboard(client)
    assert body["engine"] == "deterministic"
    shots = body["shots"]
    # 6 句台词 + 开场定场镜 + 结尾镜 = 8 镜
    assert body["shot_count"] == 8 and len(shots) == 8
    fields = {"idx", "shot_size", "visual", "action", "line_text",
              "line_speaker", "duration_sec", "engine"}
    for shot in shots:
        assert fields <= set(shot), f"缺字段: {fields - set(shot)}"
        assert shot["shot_size"] in pipeline.SHOT_SIZES
        assert shot["duration_sec"] > 0 and shot["visual"] and shot["action"]
        assert shot["engine"] == "deterministic"
    # 开场定场镜 / 结尾镜
    assert shots[0]["idx"] == 0 and shots[0]["shot_size"] == "全景"
    assert shots[0]["line_text"] is None and shots[0]["line_speaker"] is None
    assert shots[7]["idx"] == 7 and shots[7]["line_text"] is None
    # 每句一镜：文本/说话人对位，景别按句长轮换，时长按字数
    for pos, line in enumerate(LINES, start=1):
        shot = shots[pos]
        assert shot["idx"] == pos
        assert shot["line_text"] == line["text"]
        assert shot["line_speaker"] == line["speaker"]
        assert shot["shot_size"] == pipeline.SHOT_SIZES[len(line["text"]) % 4]
        assert shot["duration_sec"] == max(2, math.ceil(len(line["text"]) / 3))
    # GET 镜头表（同一场）
    resp = client.get(f"/api/v1/pipeline/storyboard/{SCENE_ID}")
    assert resp.status_code == 200 and resp.json()["shot_count"] == 8


def test_storyboard_scene_missing(client: TestClient) -> None:
    assert client.post("/api/v1/pipeline/storyboard/99999").status_code == 404
    assert client.get("/api/v1/pipeline/storyboard/99999").status_code == 404


def test_put_shot_edit(client: TestClient) -> None:
    _make_storyboard(client)
    resp = client.put(f"/api/v1/pipeline/storyboard/{SCENE_ID}/3",
                      json={"visual": "茶馆一角，烛火压低了半个画面"})
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["idx"] == 3 and updated["scene_id"] == SCENE_ID
    assert updated["shot"]["visual"] == "茶馆一角，烛火压低了半个画面"
    assert updated["shot"]["line_text"] == LINES[2]["text"]  # 未提交字段不动
    # 改一格生效，其余镜头不受影响（GET 列表按 idx 排序，idx=3 即第 4 行）
    rows = client.get(f"/api/v1/pipeline/storyboard/{SCENE_ID}").json()["shots"]
    assert rows[3]["visual"] == "茶馆一角，烛火压低了半个画面"
    assert rows[1]["visual"] != "茶馆一角，烛火压低了半个画面"
    # 景别编辑同样生效
    resp = client.put(f"/api/v1/pipeline/storyboard/{SCENE_ID}/3",
                      json={"shot_size": "特写", "duration_sec": 7})
    assert resp.status_code == 200
    assert resp.json()["shot"]["shot_size"] == "特写"
    assert resp.json()["shot"]["duration_sec"] == 7
    # 边界：不存在的 idx → 404；非法景别 → 422；空 patch → 400；未知字段 → 422
    assert client.put(f"/api/v1/pipeline/storyboard/{SCENE_ID}/99",
                      json={"visual": "x"}).status_code == 404
    assert client.put(f"/api/v1/pipeline/storyboard/{SCENE_ID}/1",
                      json={"shot_size": "大远景"}).status_code == 422
    assert client.put(f"/api/v1/pipeline/storyboard/{SCENE_ID}/1",
                      json={}).status_code == 400
    assert client.put(f"/api/v1/pipeline/storyboard/{SCENE_ID}/1",
                      json={"visualize": "x"}).status_code == 422


# ---------------------------------------------------------------- 4.2/4.3 分镜 → 三形态提示词


IMAGE_SCHEMA = {
    "type": "object",
    "required": ["form", "schema_version", "storyboard_id", "style_anchor", "shots"],
    "properties": {
        "form": {"const": "image"},
        "schema_version": {"const": "1"},
        "storyboard_id": {"type": "integer"},
        "style_anchor": {"type": "string", "minLength": 1},
        "shots": {"type": "array", "minItems": 1, "items": {
            "type": "object",
            "required": ["idx", "shot_size", "prompt", "character_id"],
            "properties": {
                "idx": {"type": "integer"},
                "shot_size": {"enum": ["全景", "中景", "近景", "特写"]},
                "prompt": {"type": "string", "minLength": 1},
                "character_id": {"type": ["integer", "null"]},
                "character_name": {"type": ["string", "null"]},
                "character_elements": {"type": "array", "items": {"type": "string"}},
            }}},
    },
}
VIDEO_SCHEMA = {
    "type": "object",
    "required": ["form", "schema_version", "storyboard_id", "shots"],
    "properties": {
        "form": {"const": "video"},
        "schema_version": {"const": "1"},
        "storyboard_id": {"type": "integer"},
        "shots": {"type": "array", "minItems": 1, "items": {
            "type": "object",
            "required": ["idx", "shot", "duration_sec", "camera_move", "character_id"],
            "properties": {
                "idx": {"type": "integer"},
                "shot": {"type": "string", "minLength": 1},
                "duration_sec": {"type": "number", "exclusiveMinimum": 0},
                "camera_move": {"type": "string", "minLength": 1},
                "character_id": {"type": ["integer", "null"]},
            }}},
    },
}
NARRATIVE_SCHEMA = {
    "type": "object",
    "required": ["form", "schema_version", "storyboard_id", "text"],
    "properties": {
        "form": {"const": "narrative"},
        "schema_version": {"const": "1"},
        "storyboard_id": {"type": "integer"},
        "text": {"type": "string", "minLength": 1},
        "word_count": {"type": "integer"},
    },
}


def _make_promptsets(client: TestClient) -> dict[int, dict]:
    resp = client.post(f"/api/v1/pipeline/prompts/{SCENE_ID}")
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["schema_version"] == "1"
    assert {p["form"] for p in created["promptsets"]} == {"image", "video", "narrative"}
    out = {}
    for p in created["promptsets"]:
        got = client.get(f"/api/v1/pipeline/prompts/{p['id']}")
        assert got.status_code == 200, got.text
        row = got.json()
        assert row["form"] == p["form"] and row["schema_version"] == "1"
        out[p["form"]] = row
    return out


def test_prompts_three_forms_schema(client: TestClient) -> None:
    # 未转分镜先导提示词 → 404
    assert client.post(f"/api/v1/pipeline/prompts/{SCENE_ID}").status_code == 404
    _make_storyboard(client)
    sets = _make_promptsets(client)

    image, video, narrative = sets["image"]["payload"], sets["video"]["payload"], sets["narrative"]["payload"]
    if HAS_JSONSCHEMA:
        jsonschema.validate(image, IMAGE_SCHEMA)
        jsonschema.validate(video, VIDEO_SCHEMA)
        jsonschema.validate(narrative, NARRATIVE_SCHEMA)

    # 手写字段断言（schema 校验之外的第二道门槛）
    assert image["form"] == "image" and image["style_anchor"]
    assert len(image["shots"]) == 8
    assert all(s["prompt"] for s in image["shots"])
    assert video["form"] == "video" and len(video["shots"]) == 8
    for s in video["shots"]:
        assert s["shot"] and s["camera_move"] and s["duration_sec"] > 0
    assert narrative["form"] == "narrative" and narrative["text"]
    assert narrative["word_count"] == len(narrative["text"])
    # 旁白覆盖整场：场刊标题与六句台词全部在场
    for needle in [BUNDLE["scene"]["heading"]] + [line["text"] for line in LINES]:
        assert needle in narrative["text"]


def test_character_consistency_injection(client: TestClient) -> None:
    _make_storyboard(client)
    sets = _make_promptsets(client)
    image = sets["image"]["payload"]
    video = sets["video"]["payload"]

    by_pos = {pos: line for pos, line in enumerate(LINES, start=1)}
    prompts_of: dict[int, list[str]] = {101: [], 102: []}
    for pos, line in by_pos.items():
        shot = image["shots"][pos]
        char = next(c for c in CHARACTERS if c["name"] == line["speaker"])
        # character_id 字段 + 要素集原文逐条注入
        assert shot["character_id"] == char["id"]
        assert shot["character_name"] == char["name"]
        for element in char["appearance_elements"]:
            assert element in shot["prompt"], f"要素集原文缺失: {element}"
        assert shot["prompt"].startswith(pipeline.STYLE_ANCHOR)  # 风格锚点
        prompts_of[char["id"]].append(shot["prompt"])
        # video 形态同样注入（spec：各镜头提示词注入同一要素集）
        vshot = video["shots"][pos]
        assert vshot["character_id"] == char["id"]
        assert all(e in vshot["shot"] for e in char["appearance_elements"])
    # 定场/收尾镜无角色 → character_id 为空且不注入任何要素
    for shot in (image["shots"][0], image["shots"][7]):
        assert shot["character_id"] is None and shot["character_elements"] == []
    # 跨镜头一致性：同一角色的注入段（要素锁定部分）逐字相同
    for cid, prompts in prompts_of.items():
        char = next(c for c in CHARACTERS if c["id"] == cid)
        lock = f"人物锁定——{char['name']}：{'；'.join(char['appearance_elements'])}"
        for prompt in prompts:
            assert lock in prompt


def test_edit_flows_downstream(client: TestClient) -> None:
    """人在环上：分镜编辑后的画面进入下一级提示词。"""
    _make_storyboard(client)
    marker = "编辑后的画面：柜台上一盏将尽的油灯"
    assert client.put(f"/api/v1/pipeline/storyboard/{SCENE_ID}/2",
                      json={"visual": marker}).status_code == 200
    sets = _make_promptsets(client)
    image = sets["image"]["payload"]
    assert marker in image["shots"][2]["prompt"]
    assert marker in sets["video"]["payload"]["shots"][2]["shot"]


# ---------------------------------------------------------------- 引擎降级 / LLM 润色


@pytest.mark.parametrize("mode", ["raise", "garbage", "none"])
def test_engine_fallback(client: TestClient, monkeypatch, mode: str) -> None:
    """KEY 在但网关抛错/坏负载/空响应 → 回退确定性版并标 engine。"""
    monkeypatch.setattr(pipeline.llm, "is_configured", lambda: True)

    def fake_chat(*_a, **_k):
        if mode == "raise":
            raise pipeline.llm.LLMError("网关超时（测试注入）")
        if mode == "garbage":
            return "抱歉，这不是 JSON"
        return None

    monkeypatch.setattr(pipeline.llm, "chat", fake_chat)
    body = _make_storyboard(client)
    assert body["engine"] == "deterministic"
    assert all(s["engine"] == "deterministic" for s in body["shots"])
    for shot in body["shots"]:  # 降级版字段完整可用
        assert shot["visual"] and shot["action"]


def test_engine_llm_polish(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(pipeline.llm, "is_configured", lambda: True)
    monkeypatch.setattr(
        pipeline.llm, "chat",
        lambda *a, **k: json.dumps(
            [{"idx": 1, "visual": "LLM 润色画面", "action": "LLM 润色动作"}],
            ensure_ascii=False),
    )
    body = _make_storyboard(client)
    assert body["engine"] == "llm"
    assert body["shots"][1]["visual"] == "LLM 润色画面"
    assert body["shots"][1]["action"] == "LLM 润色动作"
    # 景别/台词/时长仍由确定性层锁定（LLM 只润色 visual/action）
    assert body["shots"][1]["shot_size"] == pipeline.SHOT_SIZES[len(LINES[0]["text"]) % 4]
    assert body["shots"][1]["line_text"] == LINES[0]["text"]
    assert body["shots"][2]["visual"].startswith("内景·老茶馆·夜")  # 未润色镜保持原样


# ---------------------------------------------------------------- export 下载体


def test_export_download(client: TestClient) -> None:
    _make_storyboard(client)
    sets = _make_promptsets(client)
    for form, row in sets.items():
        resp = client.get(f"/api/v1/pipeline/prompts/{row['id']}/export")
        assert resp.status_code == 200
        disp = resp.headers["content-disposition"]
        assert disp.startswith("attachment;")
        assert f'filename="promptset-{row["id"]}-{form}.json"' in disp
        assert resp.headers["content-type"].startswith("application/json")
        assert json.loads(resp.text) == row["payload"]  # 纯 payload 本体
    # form 参数与实际形态不符 → 409；非法 form → 422；不存在 → 404
    image_id = sets["image"]["id"]
    assert client.get(f"/api/v1/pipeline/prompts/{image_id}/export?form=video").status_code == 409
    assert client.get(f"/api/v1/pipeline/prompts/{image_id}/export?form=other").status_code == 422
    assert client.get("/api/v1/pipeline/prompts/424242").status_code == 404


# ---------------------------------------------------------------- 上游适配（真实 screenplay 契约）


def test_load_scene_bundle_against_real_screenplay(monkeypatch) -> None:
    """适配层对真实 screenplay 五表：直插共库 → 真实 load_scene_bundle 组装正确。"""
    from fd_juchuang_api import screenplay

    monkeypatch.setattr(pipeline, "load_scene_bundle", _REAL_LOAD_SCENE_BUNDLE)
    conn = screenplay.connect()
    try:
        screenplay.migrate(conn)
        pid, cid, sid = 1, 1, 1
        conn.execute(
            "INSERT INTO projects (id, user_id, title, logline, created_at)"
            " VALUES (?,?,?,?,?)", (pid, "u1", "旧账", None, "2026-01-01"))
        conn.execute(
            "INSERT INTO characters (id, project_id, name, appearance, stance,"
            " created_at) VALUES (?,?,?,?,?,?)",
            (cid, pid, "沈青梧",
             json.dumps({"年龄感": "三十五岁上下", "着装": "月白旗袍"}, ensure_ascii=False),
             None, "2026-01-01"))
        conn.execute(
            "INSERT INTO scenes (id, project_id, idx, title, synopsis, conflict,"
            " created_at) VALUES (?,?,?,?,?,?,?)",
            (sid, pid, 1, "内景·老茶馆·夜", "对峙", None, "2026-01-01"))
        conn.execute(
            "INSERT INTO lines (id, scene_id, idx, speaker_id, text)"
            " VALUES (?,?,?,?,?)", (1, sid, 1, cid, "把账拿出来。"))
        conn.commit()
    finally:
        conn.close()

    bundle = _REAL_LOAD_SCENE_BUNDLE(sid)
    assert bundle["scene"]["id"] == sid
    assert bundle["scene"]["heading"] == "内景·老茶馆·夜"
    assert bundle["scene"]["synopsis"] == "对峙"
    assert bundle["lines"] == [{"idx": 1, "speaker": "沈青梧", "text": "把账拿出来。"}]
    assert bundle["characters"] == [{
        "id": cid, "name": "沈青梧",
        "appearance_elements": ["年龄感：三十五岁上下", "着装：月白旗袍"]}]
    with pytest.raises(HTTPException) as err:
        _REAL_LOAD_SCENE_BUNDLE(424242)
    assert err.value.status_code == 404
