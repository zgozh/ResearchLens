"""M01 — 论文、源文件、修订版、资产存储（REFACTOR_SPEC §6.3）。

公共 API 见 ``service``；跨模块只允许 import 本包的公共函数与 DTO。
"""
from .service import (  # noqa: F401
    asset_url,
    create_paper,
    create_revision,
    fetch_source,
    get_assets,
    get_metadata,
    get_paper,
    get_revision,
    get_source,
    list_papers,
    open_asset,
    publish,
    put_asset,
    set_readable,
    snapshot_for_revision,
    store_source,
)

__all__ = [
    "create_paper",
    "store_source",
    "fetch_source",
    "create_revision",
    "get_paper",
    "get_revision",
    "get_source",
    "get_assets",
    "list_papers",
    "get_metadata",
    "put_asset",
    "open_asset",
    "publish",
    "set_readable",
    "asset_url",
    "snapshot_for_revision",
]
