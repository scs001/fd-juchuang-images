"""结构化剧本工作台（task 2.1/2.2/2.3）离线测试：全流程临时 DB，不依赖网络。"""

from __future__ import annotations

import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fd_juchuang_api.screenplay import connect, migrate, router


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FD_JUCHUANG_DB", str(tmp_path / "jc-test.db"))
    # auth 的 dev-token 变量名在并行开发期有过更名（FD__AUTH_DEV_TOKENS →
    # FD_JUCHUANG_AUTH_DEV_TOKENS），两个名都设，测试对更名免疫。
    monkeypatch.setenv("FD_JUCHUANG_AUTH_DEV_TOKENS", "tok-a=u1,tok-b=u2")
    monkeypatch.setenv("FD__AUTH_DEV_TOKENS", "tok-a=u1,tok-b=u2")
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


A = {"Authorization": "Bearer tok-a"}
B = {"Authorization": "Bearer tok-b"}


def _mk_project(client, title="洞穴之喻", logline="一场关于真相与责任的对手戏"):
    r = client.post("/api/v1/screenplay/projects", headers=A,
                    json={"title": title, "logline": logline})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_character(client, pid, name, position):
    r = client.post(f"/api/v1/screenplay/projects/{pid}/characters", headers=A, json={
        "name": name,
        "appearance": {"年龄感": "四十岁上下", "体型": "清瘦挺拔", "着装": "深灰长衫",
                       "画风标签": "水墨写实"},
        "stance": {"position": position, "reasons": "多年立场", "source": None},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _mk_scene(client, pid, conflict=None):
    body = {"title": "第一场：对峙", "synopsis": "旧友重逢，立场相左"}
    if conflict:
        body["conflict"] = conflict
    r = client.post(f"/api/v1/screenplay/projects/{pid}/scenes", headers=A, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _mk_line(client, sid, speaker_id, text):
    r = client.post(f"/api/v1/screenplay/scenes/{sid}/lines", headers=A,
                    json={"speaker_id": speaker_id, "text": text})
    assert r.status_code == 201, r.text
    return r.json()


# ---- 主流程：建项目→2角色→1场次6台词→存版本→改3台词→再存→回滚逐字段一致 ----


def test_full_flow_save_edit_restore(client):
    proj = _mk_project(client)
    pid = proj["id"]
    chen = _mk_character(client, pid, "陈守拙", "真相必须公开，哪怕代价惨重")
    lin = _mk_character(client, pid, "林务实", "秩序优先，真相可以等待")
    scene = _mk_scene(client, pid, conflict={
        "positions": ["真相必须公开，哪怕代价惨重", "秩序优先，真相可以等待"],
        "source": "self:tension-1",
    })
    sid = scene["id"]
    six = [_mk_line(client, sid, chen["id"], f"第{i}句：这件事不能就这么算了。") for i in range(1, 7)]
    assert [ln["idx"] for ln in six] == [1, 2, 3, 4, 5, 6]

    # 存第一版
    v1 = client.post(f"/api/v1/screenplay/projects/{pid}/versions", headers=A).json()
    export_before = copy.deepcopy(
        client.get(f"/api/v1/screenplay/projects/{pid}/export", headers=A).json())

    # 改 3 句台词
    for i in (0, 2, 4):
        r = client.patch(f"/api/v1/screenplay/scenes/{sid}/lines/{six[i]['id']}",
                         headers=A, json={"text": f"第{i + 1}句（改）：立场变了。"})
        assert r.status_code == 200, r.text
    export_edited = client.get(f"/api/v1/screenplay/projects/{pid}/export", headers=A).json()
    assert export_edited != export_before

    # 再存一版
    v2 = client.post(f"/api/v1/screenplay/projects/{pid}/versions", headers=A).json()
    assert v1["id"] != v2["id"]

    # 回滚到第一版，逐字段一致
    r = client.post(f"/api/v1/screenplay/projects/{pid}/restore/{v1['id']}", headers=A)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["restored_to"] == v1["id"]
    export_after = client.get(f"/api/v1/screenplay/projects/{pid}/export", headers=A).json()
    assert export_after == export_before

    # 版本列表：save, save, restore（回滚动作也留了新版本）
    versions = client.get(f"/api/v1/screenplay/projects/{pid}/versions", headers=A).json()
    assert [v["action"] for v in versions] == ["save", "save", "restore"]
    assert versions[-1]["restored_from"] == v1["id"]

    # 单版本快照可取回，与回滚前第一版导出等价（去掉 meta）
    snap = client.get(f"/api/v1/screenplay/projects/{pid}/versions/{v1['id']}",
                      headers=A).json()["snapshot"]
    snap.pop("meta", None)
    assert snap == export_before


# ---- 角色要素集结构校验 ----


def test_character_appearance_needs_two_nonempty_keys(client):
    pid = _mk_project(client)["id"]
    for bad in (
        {"年龄感": "四十岁"},                              # 只有 1 个键
        {"年龄感": "", "体型": "  "},                       # 键在值全空
        {"": "清瘦", "体型": "清瘦"},                       # 空键
    ):
        r = client.post(f"/api/v1/screenplay/projects/{pid}/characters", headers=A,
                        json={"name": "路人甲", "appearance": bad})
        assert r.status_code == 422, (bad, r.text)

    # PATCH 收缩到不足 2 键同样 422
    chen = _mk_character(client, pid, "陈守拙", "真相优先")
    r = client.patch(f"/api/v1/screenplay/projects/{pid}/characters/{chen['id']}",
                     headers=A, json={"appearance": {"年龄感": "五十"}})
    assert r.status_code == 422

    # stance 结构：缺 position → 422；未知字段 → 422
    r = client.post(f"/api/v1/screenplay/projects/{pid}/characters", headers=A, json={
        "name": "乙", "appearance": {"体型": "壮", "着装": "短打"}, "stance": {"reasons": "无立场"},
    })
    assert r.status_code == 422
    r = client.post(f"/api/v1/screenplay/projects/{pid}/characters", headers=A, json={
        "name": "乙", "appearance": {"体型": "壮", "着装": "短打"},
        "stance": {"position": "中立", "extra": 1},
    })
    assert r.status_code == 422

    # 正常两角色 + 角色管理 CRUD
    chars = client.get(f"/api/v1/screenplay/projects/{pid}/characters", headers=A).json()
    assert len(chars) == 1
    r = client.patch(f"/api/v1/screenplay/projects/{pid}/characters/{chen['id']}",
                     headers=A, json={"name": "陈守拙（改）"})
    assert r.json()["name"] == "陈守拙（改）"
    r = client.delete(f"/api/v1/screenplay/projects/{pid}/characters/{chen['id']}", headers=A)
    assert r.status_code == 204
    assert client.get(f"/api/v1/screenplay/projects/{pid}/characters", headers=A).json() == []


# ---- 冲突结构校验 ----


def test_scene_conflict_structure_validation(client):
    pid = _mk_project(client)["id"]
    for bad in (
        {"positions": ["只有一方"]},
        {"positions": ["a", "b", "c"]},
        {"positions": "双方"},
        {"positions": ["a", ""]},
        {"张力": "x"},
    ):
        r = client.post(f"/api/v1/screenplay/projects/{pid}/scenes", headers=A,
                        json={"title": "场", "conflict": bad})
        assert r.status_code == 422, (bad, r.text)

    r = client.post(f"/api/v1/screenplay/projects/{pid}/scenes", headers=A, json={
        "title": "场", "conflict": {"positions": ["a", "b"], "source": "zhesi:tension-9"},
    })
    assert r.status_code == 201
    assert r.json()["conflict"] == {"positions": ["a", "b"], "source": "zhesi:tension-9"}

    # PATCH 显式置空可清除冲突
    sid = r.json()["id"]
    r = client.patch(f"/api/v1/screenplay/projects/{pid}/scenes/{sid}",
                     headers=A, json={"conflict": None})
    assert r.status_code == 200 and r.json()["conflict"] is None


# ---- 场次/台词 idx 自动排序 ----


def test_scene_and_line_auto_ordering(client):
    pid = _mk_project(client)["id"]
    s1, s2, s3 = (_mk_scene(client, pid) for _ in range(3))
    assert [s["idx"] for s in (s1, s2, s3)] == [1, 2, 3]

    client.delete(f"/api/v1/screenplay/projects/{pid}/scenes/{s2['id']}", headers=A)
    left = client.get(f"/api/v1/screenplay/projects/{pid}/scenes", headers=A).json()
    assert [(s["id"], s["idx"]) for s in left] == [(s1["id"], 1), (s3["id"], 2)]

    # 显式 idx 移动：把第 2 场提到第 1 位
    r = client.patch(f"/api/v1/screenplay/projects/{pid}/scenes/{s3['id']}",
                     headers=A, json={"idx": 1})
    assert r.status_code == 200
    moved = client.get(f"/api/v1/screenplay/projects/{pid}/scenes", headers=A).json()
    assert [s["id"] for s in moved] == [s3["id"], s1["id"]]

    # 台词：增删改 + 重排
    chen = _mk_character(client, pid, "陈", "立场A")
    sid = s3["id"]
    l1 = _mk_line(client, sid, chen["id"], "一")
    l2 = _mk_line(client, sid, chen["id"], "二")
    l3 = _mk_line(client, sid, chen["id"], "三")
    assert [ln["idx"] for ln in (l1, l2, l3)] == [1, 2, 3]

    r = client.patch(f"/api/v1/screenplay/scenes/{sid}/lines/{l3['id']}",
                     headers=A, json={"idx": 1, "text": "三（提前）"})
    assert r.status_code == 200
    lines = client.get(f"/api/v1/screenplay/scenes/{sid}/lines", headers=A).json()
    assert [(ln["id"], ln["idx"]) for ln in lines] == [(l3["id"], 1), (l1["id"], 2), (l2["id"], 3)]
    assert lines[0]["text"] == "三（提前）"

    client.delete(f"/api/v1/screenplay/scenes/{sid}/lines/{l1['id']}", headers=A)
    lines = client.get(f"/api/v1/screenplay/scenes/{sid}/lines", headers=A).json()
    assert [(ln["id"], ln["idx"]) for ln in lines] == [(l3["id"], 1), (l2["id"], 2)]

    # 台词 speaker 必须属于同项目
    other = _mk_project(client, title="别人的项目")
    stranger = _mk_character(client, other["id"], "外人", "立场X")
    r = client.post(f"/api/v1/screenplay/scenes/{sid}/lines", headers=A,
                    json={"speaker_id": stranger["id"], "text": "串场"})
    assert r.status_code == 422

    # 被台词引用的角色不可删（409）
    r = client.delete(f"/api/v1/screenplay/projects/{pid}/characters/{chen['id']}", headers=A)
    assert r.status_code == 409


# ---- 对手戏张力标注（本地版） ----


def test_tension_check_local_text_diff(client):
    pid = _mk_project(client)["id"]
    chen = _mk_character(client, pid, "陈守拙", "真相必须公开，哪怕代价惨重")
    lin = _mk_character(client, pid, "林务实", "秩序优先，真相可以等待")
    scene = _mk_scene(client, pid, conflict={
        "positions": ["真相必须公开，哪怕代价惨重", "秩序优先，真相可以等待"],
        "source": "zhesi:tension-1",
    })
    sid = scene["id"]
    _mk_line(client, sid, chen["id"], "纸包不住火。")
    _mk_line(client, sid, lin["id"], "火也会烧掉无辜的人。")

    r = client.get(f"/api/v1/screenplay/scenes/{sid}/tension-check", headers=A)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conflict"]["source"] == "zhesi:tension-1"
    assert len(body["stance_holders"]) == 2
    assert body["axis_diff"]["mode"] == "local-text-diff"
    assert body["axis_diff"]["same"] is False
    assert body["axis_diff"]["positions"] == [
        "真相必须公开，哪怕代价惨重", "秩序优先，真相可以等待"]

    # 无立场角色：本地版给空轴差而非报错
    pid2 = _mk_project(client, title="无声场")["id"]
    mute = client.post(f"/api/v1/screenplay/projects/{pid2}/characters", headers=A, json={
        "name": "哑角", "appearance": {"体型": "瘦", "着装": "灰"}}).json()
    sc2 = _mk_scene(client, pid2)
    _mk_line(client, sc2["id"], mute["id"], "……")
    r = client.get(f"/api/v1/screenplay/scenes/{sc2['id']}/tension-check", headers=A)
    assert r.status_code == 200 and r.json()["axis_diff"] is None


# ---- 用户隔离（双 token） ----


def test_user_isolation(client):
    pid = _mk_project(client)["id"]

    assert client.get("/api/v1/screenplay/projects", headers=B).json() == []
    ghost = 999999  # 数值合法但不存在的 id：走归属校验 → 404
    for method, path, payload in (
        ("get", f"/api/v1/screenplay/projects/{ghost}", None),
        ("patch", f"/api/v1/screenplay/projects/{ghost}", {"title": "x"}),
        ("delete", f"/api/v1/screenplay/projects/{ghost}", None),
        ("get", f"/api/v1/screenplay/projects/{ghost}/characters", None),
        ("post", f"/api/v1/screenplay/projects/{ghost}/characters",
         {"name": "x", "appearance": {"a": "1", "b": "2"}}),
        ("get", f"/api/v1/screenplay/projects/{ghost}/scenes", None),
        ("get", f"/api/v1/screenplay/projects/{ghost}/versions", None),
        ("get", f"/api/v1/screenplay/projects/{ghost}/export", None),
        ("post", f"/api/v1/screenplay/projects/{ghost}/versions", None),
        ("post", f"/api/v1/screenplay/projects/{ghost}/restore/{ghost}", None),
        # u1 的真实项目：u2 访问同样 404（不泄露存在性）
        ("get", f"/api/v1/screenplay/projects/{pid}", None),
        ("patch", f"/api/v1/screenplay/projects/{pid}", {"title": "偷改"}),
        ("delete", f"/api/v1/screenplay/projects/{pid}", None),
        ("get", f"/api/v1/screenplay/projects/{pid}/characters", None),
        ("post", f"/api/v1/screenplay/projects/{pid}/characters",
         {"name": "x", "appearance": {"a": "1", "b": "2"}}),
        ("get", f"/api/v1/screenplay/projects/{pid}/scenes", None),
        ("get", f"/api/v1/screenplay/projects/{pid}/versions", None),
        ("get", f"/api/v1/screenplay/projects/{pid}/export", None),
        ("post", f"/api/v1/screenplay/projects/{pid}/versions", None),
        ("post", f"/api/v1/screenplay/projects/{pid}/restore/{ghost}", None),
    ):
        kwargs = {"headers": B}
        if payload is not None:
            kwargs["json"] = payload
        r = getattr(client, method)(path, **kwargs)
        assert r.status_code == 404, (method, path, r.status_code)

    # u1 数据未被 u2 动过
    assert client.get(f"/api/v1/screenplay/projects/{pid}", headers=A).json()["id"] == pid

    # 无 token → 401
    r = client.get("/api/v1/screenplay/projects")
    assert r.status_code == 401


# ---- 项目 CRUD 与级联删除 ----


def test_project_crud_and_cascade(client):
    proj = _mk_project(client, title="旧题", logline="旧话")
    pid = proj["id"]
    r = client.patch(f"/api/v1/screenplay/projects/{pid}", headers=A,
                     json={"title": "新题", "logline": None})
    assert r.json()["title"] == "新题" and r.json()["logline"] is None

    chen = _mk_character(client, pid, "陈", "立场A")
    scene = _mk_scene(client, pid)
    _mk_line(client, scene["id"], chen["id"], "一句")
    client.post(f"/api/v1/screenplay/projects/{pid}/versions", headers=A)

    assert client.delete(f"/api/v1/screenplay/projects/{pid}", headers=A).status_code == 204
    assert client.get(f"/api/v1/screenplay/projects/{pid}", headers=A).status_code == 404

    # 级联验证：直接查库，子资源全清
    conn = connect()
    try:
        migrate(conn)
        for table, key in (("characters", "project_id"), ("scenes", "project_id"),
                           ("versions", "project_id")):
            assert conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {key}=?", (pid,)).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM lines WHERE scene_id=?", (scene["id"],)).fetchone()[0] == 0
    finally:
        conn.close()


# ---- pipeline 集成契约：scene_bundle（task 4.x 剧本→分镜上游读函数） ----


def test_scene_bundle_contract(client, monkeypatch):
    from fd_juchuang_api import pipeline, screenplay

    pid = _mk_project(client)["id"]
    chen = _mk_character(client, pid, "陈守拙", "真相优先")
    lin = _mk_character(client, pid, "林务实", "秩序优先")
    scene = _mk_scene(client, pid)
    _mk_line(client, scene["id"], chen["id"], "纸包不住火。")
    _mk_line(client, scene["id"], lin["id"], "火也会烧掉无辜的人。")

    bundle = screenplay.scene_bundle(scene["id"])
    assert bundle["scene"]["id"] == scene["id"]
    assert bundle["scene"]["heading"] == "第一场：对峙"
    assert [ln["speaker"] for ln in bundle["lines"]] == ["陈守拙", "林务实"]
    assert {c["name"] for c in bundle["characters"]} == {"陈守拙", "林务实"}
    elem = bundle["characters"][0]["appearance_elements"]
    assert all("：" in e for e in elem) and len(elem) == 4  # 键：值 形态，4 要素

    # 经 pipeline 的接缝消费（归一化后可直接用；id 可能被其侧转 str，值语义比较）
    normalized = pipeline._normalize_bundle(bundle, scene["id"])
    assert normalized["lines"][0]["speaker"] == "陈守拙"
    assert str(normalized["characters"][0]["id"]) == str(bundle["characters"][0]["id"])

    assert screenplay.scene_bundle(999999) is None


# ---- 幂等迁移：同一库上重复执行不炸、表齐 ----


def test_migration_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("FD_JUCHUANG_DB", str(tmp_path / "jc-mig.db"))
    conn = connect()
    assert migrate(conn) == 1
    assert migrate(conn) == 1  # 幂等重放无副作用
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"projects", "characters", "scenes", "lines", "versions"} <= tables
    conn.close()
