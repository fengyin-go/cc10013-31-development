"""日志审计数据集示例：按采集请求日志批次生成归档文件 ARC-55。

128 条请求按请求时间升序写入主链，主链只追加不回填。LOG-301 是本批首条请求，
其记录摘要固定为 H7K2，便于复测时逐项核对摘要顺序。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.audit import (
    TIME_FORMAT,
    build_main_node,
    record_digest,
)

ARCHIVE_FILE = "ARC-55"
DATASET_CODE = "AUD-0001"
BATCH_CODE = "BATCH-ARC-55"
DATASET_ID = 1
BATCH_SIZE = 128
FIRST_REQUEST_TIME = datetime(2026, 11, 15, 8, 0, 19)
WRITTEN_AT = "2026-11-15T08:02:30"
ENDPOINTS = ["ENDP-0001", "ENDP-0002", "ENDP-0003"]


def _record_at(index: int) -> dict[str, str]:
    """生成第 index 条请求日志；第 0 条就是 LOG-301（摘要 H7K2）。"""
    if index == 0:
        return {
            "记录编号": "LOG-301",
            "关联端点": "ENDP-0001",
            "请求时间": FIRST_REQUEST_TIME.strftime(TIME_FORMAT),
            "响应状态": "200",
            "耗时毫秒": "1127",
            "返回行数": "310",
            "错误信息": "",
            "重试次数": "0",
        }
    failed = index % 17 == 0
    request_time = (FIRST_REQUEST_TIME + timedelta(seconds=index)).strftime(TIME_FORMAT)
    return {
        "记录编号": f"LOG-{301 + index}",
        "关联端点": ENDPOINTS[index % len(ENDPOINTS)],
        "请求时间": request_time,
        "响应状态": "500" if failed else "200",
        "耗时毫秒": str(120 + (index * 37) % 880),
        "返回行数": str(50 + (index * 53) % 400),
        "错误信息": "上游超时" if failed else "",
        "重试次数": "1" if failed else "0",
    }


def build_archive_nodes() -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    prev_chain = "GENESIS"
    for index in range(BATCH_SIZE):
        record = _record_at(index)
        node = build_main_node(
            node_id=index + 1,
            ledger_seq=index + 1,
            dataset_code=DATASET_CODE,
            record=record,
            seq=index + 1,
            prev_chain=prev_chain,
            written_at=WRITTEN_AT,
        )
        nodes.append(node)
        prev_chain = str(node["链摘要"])
    return nodes


def build_audit_dataset() -> dict[str, Any]:
    nodes = build_archive_nodes()
    return {
        "id": DATASET_ID,
        "status": "收集中",
        "pending": True,
        "abnormal": False,
        "数据集编号": DATASET_CODE,
        "归档文件": ARCHIVE_FILE,
        "来源批次": BATCH_CODE,
        "采集请求数": BATCH_SIZE,
        "主节点数": BATCH_SIZE,
        "更正段数": 0,
        "摘要断点数": 0,
        "首条时间": nodes[0]["请求时间"],
        "末条时间": nodes[-1]["请求时间"],
        "尾链摘要": nodes[-1]["链摘要"],
        "建集时间": WRITTEN_AT,
        "nodes": nodes,
    }


def build_seed_tables() -> dict[str, list[dict[str, Any]]]:
    return {
        "audit": [build_audit_dataset()],
        "auditqueue": [],
    }


__all__ = [
    "ARCHIVE_FILE",
    "BATCH_CODE",
    "BATCH_SIZE",
    "DATASET_CODE",
    "FIRST_REQUEST_TIME",
    "build_audit_dataset",
    "build_archive_nodes",
    "build_seed_tables",
    "record_digest",
]
