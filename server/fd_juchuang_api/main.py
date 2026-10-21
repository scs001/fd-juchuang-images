"""剧创门面 API。

/healthz 探活、/api/version 版本。业务路由由各 feature 模块提供（子代理交付后统一挂载）。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .kernel import router as kernel_router
from .screenplay import router as screenplay_router

app = FastAPI(title="fd-juchuang-api", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(screenplay_router)
app.include_router(kernel_router)
# pipeline 行为契约未含鉴权，挂载层统一补用户隔离（J3 交接建议）
from fastapi import Depends  # noqa: E402

from . import pipeline  # noqa: E402
from .auth import require_user  # noqa: E402

app.include_router(pipeline.router, dependencies=[Depends(require_user)])


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "fd-juchuang-api", "version": __version__}


@app.get("/api/version")
def version() -> dict:
    return {"service": "fd-juchuang-api", "version": __version__}
