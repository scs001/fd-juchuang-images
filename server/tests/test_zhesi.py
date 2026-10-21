"""哲思契约消费离线测试（task 3.1/3.2/3.3）：zhesi_client 三态、映射表单元、
inject 幂等、降级后 status 明示。全离线——httpx 与 fetch_cards 均 monkeypatch，
剧本域用真 screenplay 模块 + 临时库。
"""

from __future__ import annotations

import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fd_juchuang_api import kernel, zhesi_client

# ---- 测试夹具 ---------------------------------------------------------------

AUTH = {"Authorization": "Bearer tok-a"}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db = str(tmp_path / "juchuang.db")
    monkeypatch.setenv("FD_JUCHUANG_DB", db)  # kernel 与 screenplay 共库
    # 兼容 auth.py 两种命名期（模板名 FD_JUCHUANG_ / 正名 FD_JUCHUANG_）
    monkeypatch.setenv("FD_JUCHUANG_AUTH_DEV_TOKENS", "tok-a=alice")
    monkeypatch.setenv("FD_JUCHUANG_AUTH_DEV_TOKENS", "tok-a=alice")
    # 预播种共库 schema：screenplay 用幂等 IF NOT EXISTS DDL（不碰计数器），
    # audit_log 归 personal.migrate（user_version 由其独占持有——见其迁移注释）
    from fd_juchuang_api import screenplay

    conn = screenplay.connect()
    screenplay.migrate(conn)
    conn.close()
    try:
        from fd_juchuang_api import personal

        conn = personal.connect()
        personal.migrate(conn)
        conn.close()
    except Exception:  # noqa: BLE001 —— personal 未交付时 kernel 测试不受影响
        pass
    a = FastAPI()
    a.include_router(kernel.router)
    return a


@pytest.fixture()
def client(app):
    return TestClient(app)


def _cards() -> list[dict]:
    return [
        {
            "id": "c1",
            "question": "Free will: compatibilism, libertarianism, or no free will?",
            "question_ref": "survey-2020:free will",
            "position": "libertarianism",
            "stability": "stable",
            "strongest_objection": "运气问题：决定论下初始条件不由agent负责",
            "as_of": "2026-10-01T00:00:00+00:00",
        },
        {
            "id": "c2",
            "question": "Free will: compatibilism, libertarianism, or no free will?",
            "question_ref": "survey-2020:free will",
            "position": "no free will",
            "stability": "testing",
            "strongest_objection": "道德责任感与能动性现象学",
            "as_of": "2026-10-02T00:00:00+00:00",
        },
    ]


def _tensions() -> list[dict]:
    return [
        {
            "id": "t1",
            "card_ids": ["c1", "c2"],
            "description": "同持自由意志论与「无自由意志」：自由意志是否存在，直接对立。",
            "source": "经典张力: 形而上学自由意志论与硬决定论之争（Kane vs Pereboom/Honderich）。",
        }
    ]


def _fetch_ok(cards=None, tensions=None):
    return lambda token: (cards if cards is not None else _cards(),
                          tensions if tensions is not None else _tensions())


def _fetch_not_authorized():
    def fake(token):
        raise zhesi_client.NotAuthorized("zhesi http 403: 用户未对 juchuang 开放立场卡")
    return fake


def _fetch_unavailable():
    def fake(token):
        raise zhesi_client.Unavailable("zhesi unreachable: ReadTimeout")
    return fake


def _make_project(client) -> str:
    from fd_juchuang_api import screenplay

    proj = screenplay.create_project(screenplay.ProjectIn(title="自由意志双声部"), "alice")
    return proj["id"]


# ---- zhesi_client 三态（monkeypatch httpx.get，不起服务） --------------------


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _patch_get(monkeypatch, fake):
    monkeypatch.setattr(zhesi_client.httpx, "get", fake)


def test_fetch_cards_ok(monkeypatch):
    payload = {"contract_version": "1", "consumer": "juchuang",
               "cards": _cards(), "tensions": _tensions()}
    calls = {}

    def fake(url, **kw):
        calls["url"] = url
        calls["params"] = kw.get("params")
        calls["auth"] = kw["headers"]["Authorization"]
        return _Resp(200, payload)

    _patch_get(monkeypatch, fake)
    cards, tensions = zhesi_client.fetch_cards("tok-a")
    assert len(cards) == 2 and len(tensions) == 1
    assert calls["params"] == {"consumer": "juchuang"}
    assert calls["auth"] == "Bearer tok-a"  # 用户令牌原样透传
    assert calls["url"].endswith("/api/v1/contract/cards")


def test_fetch_cards_not_authorized(monkeypatch):
    _patch_get(monkeypatch, lambda url, **kw: _Resp(403, {"detail": "用户未对 juchuang 开放立场卡"}))
    with pytest.raises(zhesi_client.NotAuthorized):
        zhesi_client.fetch_cards("tok-a")


def test_fetch_cards_timeout(monkeypatch):
    def fake(url, **kw):
        raise httpx.ReadTimeout("timed out")
    _patch_get(monkeypatch, fake)
    with pytest.raises(zhesi_client.Unavailable):
        zhesi_client.fetch_cards("tok-a")


def test_fetch_cards_5xx_and_bad_contract(monkeypatch):
    _patch_get(monkeypatch, lambda url, **kw: _Resp(503, {}))
    with pytest.raises(zhesi_client.Unavailable):
        zhesi_client.fetch_cards("tok-a")
    _patch_get(monkeypatch, lambda url, **kw: _Resp(200, {"contract_version": "2", "cards": []}))
    with pytest.raises(zhesi_client.Unavailable):
        zhesi_client.fetch_cards("tok-a")
    _patch_get(monkeypatch, lambda url, **kw: _Resp(200, None))  # 坏 JSON
    with pytest.raises(zhesi_client.Unavailable):
        zhesi_client.fetch_cards("tok-a")


# ---- 映射表单元（纯函数） ---------------------------------------------------


def test_map_tension_to_conflict():
    conflict = kernel.map_tension_to_conflict(_tensions()[0],
                                              {c["id"]: c for c in _cards()})
    assert conflict["zhesi_tension_ref"] == "zhesi:tension:t1"
    assert conflict["source"].startswith("zhesi:tension:t1")
    assert "Kane vs Pereboom" in conflict["source"]
    assert conflict["positions"] == [
        "Free will: compatibilism, libertarianism, or no free will?：libertarianism",
        "Free will: compatibilism, libertarianism, or no free will?：no free will",
    ]
    assert [s["card_id"] for s in conflict["sides"]] == ["c1", "c2"]


def test_map_tension_unmappable_when_one_side_missing():
    # 对方立场卡未授权/不存在 → 不写残缺冲突
    assert kernel.map_tension_to_conflict(_tensions()[0], {"c1": _cards()[0]}) is None


def test_map_card_to_stance():
    product = kernel.map_card_to_stance(_cards()[0])
    assert product["zhesi_card_ref"] == "zhesi:c1"
    stance = product["stance"]
    assert set(stance) == {"position", "reasons", "source"}  # StanceModel 口径
    assert stance["position"] == "libertarianism"
    assert stance["source"] == "zhesi:c1"
    assert "对手戏弹药（最强反驳）：运气问题" in stance["reasons"]  # 弹药保留
    assert "as_of 2026-10-01" in stance["reasons"]  # as_of 保留
    assert product["as_of"] == "2026-10-01T00:00:00+00:00"
    assert product["ammunition"].startswith("运气问题")


def test_build_mapped_products_reports_unmappable():
    products = kernel.build_mapped_products([_cards()[0]], _tensions())
    assert products["unmappable_tensions"] == ["zhesi:tension:t1"]
    assert products["conflicts"] == []
    assert len(products["stances"]) == 1


# ---- /link /status /inject 全链（真 screenplay 域 + 临时库） -----------------


def test_link_ok_returns_mapping_summary(client, monkeypatch):
    monkeypatch.setattr(kernel.zhesi_client, "fetch_cards", _fetch_ok())
    resp = client.post("/api/v1/kernel/link", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "linked"
    assert body["kernel_map_version"] == "1"
    assert body["cards"] == 2 and body["tensions"] == 1
    assert body["conflicts"][0]["zhesi_tension_ref"] == "zhesi:tension:t1"
    assert body["conflicts"][0]["positions"] == [
        "Free will: compatibilism, libertarianism, or no free will?：libertarianism",
        "Free will: compatibilism, libertarianism, or no free will?：no free will",
    ]
    assert {s["zhesi_card_ref"] for s in body["stances"]} == {"zhesi:c1", "zhesi:c2"}

    status = client.get("/api/v1/kernel/status", headers=AUTH).json()
    assert status["mode"] == "linked"
    assert status["cached_cards"] == 2 and status["cached_tensions"] == 1
    assert status["last_error"] is None


def test_link_not_authorized_degrades(client, monkeypatch):
    monkeypatch.setattr(kernel.zhesi_client, "fetch_cards", _fetch_not_authorized())
    resp = client.post("/api/v1/kernel/link", headers=AUTH)
    assert resp.status_code == 200  # 降级不是错误：创作不阻断
    body = resp.json()
    assert body["mode"] == "standalone"
    assert body["reason"].startswith("not_authorized:")

    status = client.get("/api/v1/kernel/status", headers=AUTH).json()
    assert status["mode"] == "standalone"
    assert status["cached_cards"] == 0  # 授权收回：缓存清空
    assert status["last_error"].startswith("not_authorized:")


def test_link_unavailable_keeps_cache_and_status_shows_reason(client, monkeypatch):
    monkeypatch.setattr(kernel.zhesi_client, "fetch_cards", _fetch_ok())
    client.post("/api/v1/kernel/link", headers=AUTH)

    monkeypatch.setattr(kernel.zhesi_client, "fetch_cards", _fetch_unavailable())
    resp = client.post("/api/v1/kernel/link", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["mode"] == "standalone"
    assert resp.json()["reason"].startswith("unavailable:")

    status = client.get("/api/v1/kernel/status", headers=AUTH).json()
    assert status["mode"] == "standalone"  # 降级明示
    assert status["last_error"].startswith("unavailable:")
    assert status["cached_cards"] == 2  # 契约不可达不清缓存（补挂面）


def test_inject_writes_conflict_and_stance_then_idempotent(client, monkeypatch):
    from fd_juchuang_api import screenplay

    pid = _make_project(client)
    monkeypatch.setattr(kernel.zhesi_client, "fetch_cards", _fetch_ok())
    assert client.post("/api/v1/kernel/link", headers=AUTH).json()["mode"] == "linked"

    first = client.post(f"/api/v1/kernel/inject/{pid}", headers=AUTH)
    assert first.status_code == 200
    body = first.json()
    assert body["mode"] == "linked"
    counts = body["injected"]["counts"]
    assert counts == {"scenes_created": 1, "scenes_skipped": 0,
                      "characters_created": 2, "characters_skipped": 0}
    assert body["injected"]["scenes"][0]["zhesi_tension_ref"] == "zhesi:tension:t1"
    assert {c["zhesi_card_ref"] for c in body["injected"]["characters"]} == {"zhesi:c1", "zhesi:c2"}

    # 落库校验：经 screenplay 读回，conflict/stance 均含哲思卡可溯 ref
    scenes = screenplay.list_scenes(pid, "alice")
    assert len(scenes) == 1
    conflict = scenes[0]["conflict"]
    assert conflict["source"].startswith("zhesi:tension:t1")
    assert conflict["positions"][0].endswith("libertarianism")
    assert conflict["positions"][1].endswith("no free will")
    characters = screenplay.list_characters(pid, "alice")
    assert {c["stance"]["source"] for c in characters} == {"zhesi:c1", "zhesi:c2"}
    by_pos = {c["stance"]["position"]: c for c in characters}
    assert "对手戏弹药（最强反驳）：运气问题" in by_pos["libertarianism"]["stance"]["reasons"]

    # 幂等：同 zhesi ref 不重复写（场景/角色数量不变，全部 skipped）
    second = client.post(f"/api/v1/kernel/inject/{pid}", headers=AUTH)
    assert second.status_code == 200
    counts2 = second.json()["injected"]["counts"]
    assert counts2 == {"scenes_created": 0, "scenes_skipped": 1,
                       "characters_created": 0, "characters_skipped": 2}
    assert len(screenplay.list_scenes(pid, "alice")) == 1
    assert len(screenplay.list_characters(pid, "alice")) == 2


def test_inject_missing_project_404(client, monkeypatch):
    monkeypatch.setattr(kernel.zhesi_client, "fetch_cards", _fetch_ok())
    client.post("/api/v1/kernel/link", headers=AUTH)
    resp = client.post("/api/v1/kernel/inject/no-such-project", headers=AUTH)
    assert resp.status_code == 404


def test_inject_after_unavailable_uses_last_cache(client, monkeypatch):
    """Unavailable 降级后：状态明示 standalone，但保留的最后映射仍可补挂注入。"""
    from fd_juchuang_api import screenplay

    pid = _make_project(client)
    monkeypatch.setattr(kernel.zhesi_client, "fetch_cards", _fetch_ok())
    client.post("/api/v1/kernel/link", headers=AUTH)

    monkeypatch.setattr(kernel.zhesi_client, "fetch_cards", _fetch_unavailable())
    client.post("/api/v1/kernel/link", headers=AUTH)  # 契约断 → 降级
    assert client.get("/api/v1/kernel/status", headers=AUTH).json()["mode"] == "standalone"

    resp = client.post(f"/api/v1/kernel/inject/{pid}", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["mode"] == "standalone"  # 如实明示当前模式
    assert resp.json()["injected"]["counts"]["scenes_created"] == 1
    assert len(screenplay.list_scenes(pid, "alice")) == 1


def test_inject_never_linked_returns_standalone_empty(client):
    pid = _make_project(client)
    resp = client.post(f"/api/v1/kernel/inject/{pid}", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "standalone"
    assert body["reason"] == "never linked"
    assert body["injected"]["scenes"] == []

    status = client.get("/api/v1/kernel/status", headers=AUTH).json()
    assert status["mode"] == "standalone" and status["cached_cards"] == 0


def test_users_are_isolated(client, monkeypatch, tmp_path):
    monkeypatch.setenv("FD_JUCHUANG_AUTH_DEV_TOKENS", "tok-a=alice,tok-b=bob")
    monkeypatch.setenv("FD_JUCHUANG_AUTH_DEV_TOKENS", "tok-a=alice,tok-b=bob")
    monkeypatch.setattr(kernel.zhesi_client, "fetch_cards", _fetch_ok())
    client.post("/api/v1/kernel/link", headers=AUTH)
    bob_status = client.get("/api/v1/kernel/status",
                            headers={"Authorization": "Bearer tok-b"}).json()
    assert bob_status["mode"] == "standalone" and bob_status["cached_cards"] == 0


def test_kernel_state_table_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("FD_JUCHUANG_DB", str(tmp_path / "k.db"))
    conn = kernel.connect()
    kernel.migrate(conn)
    kernel.set_state(conn, "alice", "linked", {"cards": [1, 2], "tensions": []}, None)
    state = kernel.get_state(conn, "alice")
    assert state["mode"] == "linked"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(kernel_state)")}
    assert cols == {"id", "user_id", "mode", "cards_cache", "updated_at"}
    # 与 screenplay 共库：五张剧本表与 kernel_state 同库共存
    screenplay_tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    conn.close()
    assert "kernel_state" in screenplay_tables
