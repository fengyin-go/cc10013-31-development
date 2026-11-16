"""日志审计数据集接口：批次建集、只写一次、摘要链校验、导出与复测。

审计交付待处理队列的接口和数据集放在同一组路由下（/api/audit/queue），
因为队列项的生命周期只跟摘要断点绑定。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, PageResult, RecordPayload
from app.services.audit import service

router = APIRouter(prefix="/api/audit", tags=["日志审计"])

LIST_FIELDS = [
    "数据集编号",
    "归档文件",
    "来源批次",
    "采集请求数",
    "主节点数",
    "更正段数",
    "摘要断点数",
    "首条时间",
]
STATUSES = ["收集中", "待裁决", "已封存"]
QUEUE_STATUSES = ["待处理", "已交付", "已关闭"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按数据集编号或归档文件检索"),
    status: str | None = Query(default=None, description="收集中、待裁决、已封存"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号与状态过滤日志审计数据集；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/queue", response_model=PageResult[dict])
def list_queue(
    keyword: str | None = Query(default=None, description="按队列编号、记录编号或归档文件检索"),
    status: str | None = Query(default=None, description="待处理、已交付、已关闭"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """审计交付待处理队列：收存摘要断点与顺序异常，供交付环节逐条确认。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_queue(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/queue/{entry_id}", response_model=dict)
def get_queue_entry(entry_id: int) -> dict:
    entry = service.get_queue_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"审计交付待处理队列项 {entry_id} 不存在")
    return entry


@router.post("/queue/{entry_id}/actions", response_model=ActionResult)
def run_queue_action(entry_id: int, payload: RecordPayload) -> ActionResult:
    """确认交付或关闭队列项；不允许的动作会被拦下并说明原因。"""
    action = str(payload.merged_values().get("action") or "").strip()
    entry, message = service.run_queue_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取数据集明细：包含节点台账、摘要断点、冲突裁决与链校验结果。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"日志审计数据集 {entry_id} 不存在")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: RecordPayload) -> ActionResult:
    """按采集请求日志批次建立日志审计数据集；缺归档文件时说明原因。"""
    entry, missing = service.create_entry(payload.merged_values())
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="日志审计数据集已建立，主链按写入顺序生成", entry=entry)


@router.post("/{entry_id}/records", response_model=ActionResult)
def ingest_record(entry_id: int, payload: RecordPayload) -> ActionResult:
    """写入一条请求日志：相同记录只写一次，迟到记录进入裁决与交付队列。

    请求体既可以是 {"values": {...}}，也可以直接给出日志字段。
    """
    values = payload.merged_values()
    result, message, _ = service.ingest(entry_id, values)
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: RecordPayload) -> ActionResult:
    """执行校验摘要链、裁决冲突、封存数据集、解封数据集。

    请求体可以写成 {"action": "..."} 平铺，也可以放进 values。
    """
    values = payload.merged_values()
    action = str(values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/{entry_id}/verify", response_model=dict)
def verify(entry_id: int) -> dict[str, Any]:
    """逐条重算主链摘要并核对条数与断点，返回可复核的检查清单。"""
    verification = service.verify(entry_id)
    if verification.get("checks") == []:
        raise HTTPException(status_code=404, detail=f"日志审计数据集 {entry_id} 不存在")
    return verification


@router.get("/{entry_id}/export", response_model=dict)
def export_detail(entry_id: int) -> dict[str, Any]:
    """导出批次详情：记录按归档顺序逐条列出，并同步列出摘要断点。"""
    detail = service.export_detail(entry_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"日志审计数据集 {entry_id} 不存在")
    return detail


@router.post("/{entry_id}/recheck", response_model=dict)
def recheck(entry_id: int) -> dict[str, Any]:
    """复测：重复写入同一条日志并补一条迟到更正，观察主节点数与更正段指向。"""
    result = service.recheck(entry_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"日志审计数据集 {entry_id} 不存在")
    return result
