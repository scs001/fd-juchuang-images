"""剧创 E2E 验收剧本（task 5.1）：双账号全链 + 降级独立模式。

链路：建项目→角色（要素+立场）→场次（conflict）→台词→版本快照→改→回滚→
导出；底料：分镜→三形态提示词（角色一致性）；哲思：无哲思侧时
降级 standalone（创作不阻断）。双账号隔离互查。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def call(base: str, token: str, method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        r = urllib.request.urlopen(req, timeout=60)
        raw = r.read()
        return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def first_id(obj: dict, *keys: str) -> str:
    for k in keys:
        v = obj.get(k)
        if isinstance(v, dict) and "id" in v:
            return str(v["id"])
        if v is not None:
            return str(v)
    raise AssertionError(f"找不到 id: {str(obj)[:160]}")


def run_account(base: str, token: str, who: str) -> str:
    code, proj = call(base, token, "POST", "/api/v1/screenplay/projects",
                      {"title": f"{who} 的戏", "logline": "旧账与旧友"})
    assert code in (200, 201), f"{who} 建项目 {code}: {proj}"
    pid = first_id(proj, "id", "project")

    chars = []
    for name, stance in [("沈青梧", "libertarianism"), ("顾行舟", "no free will")]:
        code, c = call(base, token, "POST", f"/api/v1/screenplay/projects/{pid}/characters",
                       {"name": name,
                        "appearance": {"年龄感": "三十五岁上下", "着装": "月白旗袍", "画风": "水墨淡彩"},
                        "stance": {"position": stance, "reasons": f"{who} 设定"}})
        assert code in (200, 201), f"{who} 角色 {code}: {c}"
        chars.append(first_id(c, "id", "character"))
    print(f"[{who}] 项目+2 角色 ok")

    code, sc = call(base, token, "POST", f"/api/v1/screenplay/projects/{pid}/scenes",
                    {"title": "茶馆对峙",
                     "conflict": {"positions": ["要账", "赖账"], "source": "手工设定"}})
    assert code in (200, 201), f"{who} 场次 {code}: {sc}"
    sid = first_id(sc, "id", "scene")
    for i, (sp, txt) in enumerate([
        (chars[0], "把账拿出来。"), (chars[1], "什么账，我听不懂你在说什么。"),
        (chars[0], "十年前腊月，城南当铺。"), (chars[1], "当票早烧了。"),
        (chars[0], "烧得掉纸，烧不掉印。"), (chars[1], "那你就去告。"),
    ]):
        code, _ = call(base, token, "POST", f"/api/v1/screenplay/scenes/{sid}/lines",
                       {"speaker_id": sp, "text": txt})
        assert code in (200, 201), f"{who} 台词{i} {code}"
    print(f"[{who}] 场次+6 台词 ok")

    code, v1 = call(base, token, "POST", f"/api/v1/screenplay/projects/{pid}/versions", {})
    assert code in (200, 201), f"{who} 存 v1 {code}: {v1}"
    vid1 = first_id(v1, "id", "version")
    code, lines = call(base, token, "GET", f"/api/v1/screenplay/scenes/{sid}/lines")
    lst = lines if isinstance(lines, list) else lines.get("lines") or lines.get("results") or []
    lid = first_id(lst[0], "id")
    call(base, token, "PUT", f"/api/v1/screenplay/scenes/{sid}/lines/{lid}", {"text": "改过的台词"})
    call(base, token, "POST", f"/api/v1/screenplay/projects/{pid}/versions", {})
    code, _ = call(base, token, "POST", f"/api/v1/screenplay/projects/{pid}/restore/{vid1}", {})
    assert code in (200, 201), f"{who} 回滚 {code}"
    code, lines2 = call(base, token, "GET", f"/api/v1/screenplay/scenes/{sid}/lines")
    lst2 = lines2 if isinstance(lines2, list) else lines2.get("lines") or []
    assert any("把账拿出来" in str(x.get("text")) for x in lst2), f"{who} 回滚未复原"
    print(f"[{who}] 版本快照/回滚 ok")

    code, exp = call(base, token, "GET", f"/api/v1/screenplay/projects/{pid}/export")
    assert code == 200 and "scenes" in json.dumps(exp), f"{who} 导出 {code}"
    print(f"[{who}] 导出 ok")

    code, sb = call(base, token, "POST", f"/api/v1/pipeline/storyboard/{sid}", {})
    assert code in (200, 201), f"{who} 分镜 {code}: {sb}"
    sbj = json.dumps(sb, ensure_ascii=False)
    shots = (sb.get("shots") if isinstance(sb, dict) else None) or []
    print(f"[{who}] 分镜 ok（{len(shots) if shots else sbj.count('idx')} 镜, engine={sb.get('engine') if isinstance(sb, dict) else '?'})")
    code, ps = call(base, token, "POST", f"/api/v1/pipeline/prompts/{sid}", {})
    assert code in (200, 201), f"{who} 提示词 {code}: {ps}"
    refs = ps if isinstance(ps, list) else ps.get("promptsets") or ps.get("results") or []
    assert refs, f"{who} 提示词引用为空: {ps}"
    psj = ""
    for ref in refs:
        psid = ref.get("id") or ref.get("promptset_id")
        code, payload = call(base, token, "GET", f"/api/v1/pipeline/prompts/{psid}")
        assert code == 200, f"{who} 取提示词 {code}"
        psj += json.dumps(payload, ensure_ascii=False)
    assert ("月白旗袍" in psj) or ("character_id" in psj), f"{who} 角色一致性未注入"
    print(f"[{who}] 三形态提示词 ok（{len(refs)} 形态，角色要素注入实证）")
    return pid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8016")
    args = ap.parse_args()

    a = run_account(args.base, "tok-a", "alice")
    b = run_account(args.base, "tok-b", "bob")

    code, out = call(args.base, "tok-b", "GET", "/api/v1/screenplay/projects")
    lst = out if isinstance(out, list) else out.get("projects") or out.get("results") or []
    assert all(str(p.get("id")) != a for p in lst), "隔离失败"
    print("[隔离] bob 看不到 alice 的项目")

    code, st = call(args.base, "tok-a", "POST", "/api/v1/kernel/link", {})
    assert code == 200, f"link {code}: {st}"
    assert st.get("mode") == "standalone" and st.get("reason"), f"降级语义不对: {st}"
    print(f"[降级] 无哲思侧 → standalone（reason={str(st.get('reason'))[:50]}…）")

    print("\n剧创 E2E 双账号全链通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
