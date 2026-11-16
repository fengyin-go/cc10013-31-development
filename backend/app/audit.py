"""日志审计摘要工具：规范化请求日志、计算记录摘要与只增不改的链式摘要。

这里的函数只依赖标准库，既给示例数据生成用，也给业务规则与校验用，避免出现
“写入时一套算法、校验时另一套算法”的情况。
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime
from typing import Any

# 归档摘要只覆盖请求日志的固定字段；字段顺序即摘要顺序，调整顺序会让历史摘要失效。
RECORD_FIELDS = [
    "记录编号",
    "关联端点",
    "请求时间",
    "响应状态",
    "耗时毫秒",
    "返回行数",
    "错误信息",
    "重试次数",
]
REQUIRED_FIELDS = ["记录编号", "关联端点", "请求时间"]
GENESIS = "GENESIS"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


def normalize_time(value: Any) -> str:
    """把请求时间规范成 2026-11-15T08:00:19；无法解析时返回空串。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return ""
    return parsed.strftime(TIME_FORMAT)


def normalize_record(values: dict[str, Any]) -> dict[str, str]:
    """只保留摘要字段，空值统一成空串，保证相同内容得到相同摘要。"""
    record: dict[str, str] = {}
    for field in RECORD_FIELDS:
        value = values.get(field)
        if value is None:
            record[field] = ""
        else:
            record[field] = str(value).strip()
    return record


def canonical_record(record: dict[str, Any]) -> str:
    """把一条日志压成摘要原文，字段顺序固定，便于人工复核。"""
    return "|".join(f"{field}={record.get(field, '') or ''}" for field in RECORD_FIELDS)


def record_digest(record: dict[str, Any]) -> tuple[str, str]:
    """返回（短摘要, 完整摘要）。短摘要用于展示与逐条对应，完整摘要用于留痕。"""
    full = hashlib.sha256(canonical_record(record).encode("utf-8")).hexdigest()
    short = base64.b32encode(bytes.fromhex(full)).decode("ascii")[:4]
    return short, full


def chain_digest(seq_label: str, prev_chain: str, rec_digest: str, code: str, request_time: str) -> str:
    """链摘要同时绑定顺序、前序、记录摘要与记录定位信息，任何一项变化都会断链。"""
    material = f"{seq_label}|{prev_chain}|{rec_digest}|{code}|{request_time}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16].upper()


def main_seq_label(seq: int) -> str:
    return f"M{seq:04d}"


def correction_seq_label(ledger_seq: int) -> str:
    return f"C{ledger_seq:04d}"


def build_main_node(
    *,
    node_id: int,
    ledger_seq: int,
    dataset_code: str,
    record: dict[str, str],
    seq: int,
    prev_chain: str,
    written_at: str,
) -> dict[str, Any]:
    """构造一个主链节点；主链只追加，序号与请求时间都不回填。"""
    digest, full = record_digest(record)
    chain = chain_digest(main_seq_label(seq), prev_chain, digest, record["记录编号"], record["请求时间"])
    return {
        "id": node_id,
        "节点编号": f"N-{node_id:04d}",
        "数据集编号": dataset_code,
        "台账序号": ledger_seq,
        "节点类型": "主节点",
        "主链序号": seq,
        "记录编号": record["记录编号"],
        "请求时间": record["请求时间"],
        "记录摘要": digest,
        "摘要指纹": full,
        "前序摘要": prev_chain,
        "链摘要": chain,
        "归属节点": None,
        "记录内容": dict(record),
        "断点": False,
        "断点原因": None,
        "队列编号": None,
        "裁决编号": None,
        "顺序异常": False,
        "写入时间": written_at,
    }


def build_correction_node(
    *,
    node_id: int,
    ledger_seq: int,
    dataset_code: str,
    record: dict[str, str],
    original: dict[str, Any],
    reason: str,
    queue_code: str,
    conflict_code: str,
    written_at: str,
) -> dict[str, Any]:
    """迟到更正只追加“更正段”，锚定原主节点，不参与主链排序、不新增主节点。"""
    digest, full = record_digest(record)
    chain = chain_digest(
        correction_seq_label(ledger_seq),
        str(original.get("链摘要") or ""),
        digest,
        record["记录编号"],
        record["请求时间"],
    )
    return {
        "id": node_id,
        "节点编号": f"N-{node_id:04d}",
        "数据集编号": dataset_code,
        "台账序号": ledger_seq,
        "节点类型": "更正段",
        "主链序号": None,
        "记录编号": record["记录编号"],
        "请求时间": record["请求时间"],
        "记录摘要": digest,
        "摘要指纹": full,
        "前序摘要": original.get("链摘要"),
        "链摘要": chain,
        "归属节点": original.get("节点编号"),
        "记录内容": dict(record),
        "断点": True,
        "断点原因": reason,
        "队列编号": queue_code,
        "裁决编号": conflict_code,
        "顺序异常": False,
        "写入时间": written_at,
    }


def main_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按主链序号返回主节点，导出与校验都只认这一种顺序。"""
    return sorted(
        (node for node in nodes if node.get("节点类型") == "主节点"),
        key=lambda node: int(node.get("主链序号") or 0),
    )


def correction_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (node for node in nodes if node.get("节点类型") == "更正段"),
        key=lambda node: int(node.get("台账序号") or 0),
    )


def build_export_rows(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """导出明细严格按归档顺序（主链序号）生成，每条都带归档摘要。"""
    rows: list[dict[str, Any]] = []
    for node in main_nodes(nodes):
        rows.append({
            "序号": int(node["主链序号"]),
            "节点编号": node["节点编号"],
            "记录编号": node.get("记录编号"),
            "请求时间": node.get("请求时间"),
            "记录摘要": node.get("记录摘要"),
            "归档摘要": node.get("记录摘要"),
            "前序摘要": node.get("前序摘要"),
            "链摘要": node.get("链摘要"),
            "顺序异常": bool(node.get("顺序异常")),
        })
    return rows
