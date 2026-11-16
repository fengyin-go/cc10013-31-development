"""日志审计数据集业务规则：批次建集、只写一次、摘要链、迟到裁决与交付队列。

几条硬约束都收在这里，路由层只做参数转发：

1. 同一数据集内，记录编号与记录摘要都相同的请求日志只写入一次；
2. 主链只追加，主链序号一旦写入不再重排，导出批次按主链序号读取；
3. 归档末尾收到请求时间更早的日志时，先登记冲突与裁决记录，
   主节点/更正段只追加不覆盖，链始终可以重算校验；
4. 每个摘要断点都要进入审计交付待处理队列，导出详情同步列出。
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from app.audit import (
    GENESIS,
    RECORD_FIELDS,
    REQUIRED_FIELDS,
    TIME_FORMAT,
    build_correction_node,
    build_export_rows,
    build_main_node,
    chain_digest,
    correction_nodes,
    main_nodes,
    main_seq_label,
    normalize_record,
    normalize_time,
    record_digest,
)
from app.store import store

MODULE = "audit"
QUEUE_MODULE = "auditqueue"
STATUS_ORDER = ["收集中", "待裁决", "已封存"]
ACTION_RULES = {"封存数据集": "已封存", "解封数据集": "收集中"}
QUEUE_STATUS = ["待处理", "已交付", "已关闭"]
QUEUE_ACTIONS = {"确认交付": "已交付", "关闭队列项": "已关闭"}


def _now() -> str:
    return datetime.now().strftime(TIME_FORMAT)


class AuditService:
    # ------------------------------------------------------------------ 数据集
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._summary(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("数据集编号", "")) or keyword in str(row.get("归档文件", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        dataset = store.find(MODULE, entry_id)
        if dataset is None:
            return None
        detail = copy.deepcopy(dataset)
        detail["摘要断点"] = self.breakpoints(detail)
        detail["待裁决冲突"] = [
            item for item in detail.get("conflicts", []) if item.get("状态") == "待裁决"
        ]
        detail["校验"] = self.verify(entry_id)
        return detail

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        archive_file = str(values.get("归档文件") or "").strip()
        if not archive_file:
            return None, ["归档文件"]
        rows = store.rows(MODULE)
        dataset_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        dataset = {
            "id": dataset_id,
            "status": "收集中",
            "pending": True,
            "abnormal": False,
            "数据集编号": f"AUD-{dataset_id:04d}",
            "归档文件": archive_file,
            "来源批次": str(values.get("来源批次") or f"BATCH-{archive_file}").strip(),
            "采集请求数": 0,
            "主节点数": 0,
            "更正段数": 0,
            "摘要断点数": 0,
            "首条时间": None,
            "末条时间": None,
            "尾链摘要": GENESIS,
            "建集时间": _now(),
            "nodes": [],
            "conflicts": [],
        }
        rows.append(dataset)
        records: list[dict[str, Any]] = []
        source_log_ids = values.get("采集日志记录") or []
        if isinstance(source_log_ids, list):
            by_id = {int(row.get("id", 0)): row for row in store.rows("log")}
            for log_id in source_log_ids:
                try:
                    row = by_id.get(int(log_id))
                except (TypeError, ValueError):
                    row = None
                if row is not None:
                    records.append({field: row.get(field) for field in RECORD_FIELDS})
                else:
                    dataset.setdefault("warnings", []).append(f"采集日志 {log_id} 不存在，已跳过")
        for record in values.get("记录列表") or values.get("records") or []:
            if isinstance(record, dict):
                records.append(record)
        for record in records:
            self.ingest(dataset_id, record)
        self._refresh(dataset)
        return dataset, []

    # ------------------------------------------------------------------ 写入
    def ingest(self, dataset_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
        dataset = store.find(MODULE, dataset_id)
        if dataset is None:
            return None, f"日志审计数据集 {dataset_id} 不存在", {}
        return self._ingest_into(dataset, values, queue_sink=store.rows(QUEUE_MODULE))

    def _ingest_into(
        self,
        dataset: dict[str, Any],
        values: dict[str, Any],
        *,
        queue_sink: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
        """写入一条请求日志；相同记录不再追加，迟到记录走冲突裁决。

        queue_sink 允许复测时把摘要断点写进隔离的队列副本，避免污染正式交付队列。
        """
        record = normalize_record(values)
        missing = [field for field in REQUIRED_FIELDS if not record.get(field)]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}", {}
        if dataset.get("status") == STATUS_ORDER[-1]:
            return None, f"数据集 {dataset.get('数据集编号')} 已封存，只能通过复测接口在副本上验证", {}
        request_time = normalize_time(record["请求时间"])
        if not request_time:
            return None, f"请求时间「{values.get('请求时间')}」无法识别，需为 YYYY-MM-DDTHH:MM:SS", {}
        record["请求时间"] = request_time
        digest, full = record_digest(record)
        dataset.setdefault("nodes", [])
        dataset.setdefault("conflicts", [])
        mains = main_nodes(dataset["nodes"])

        # 1) 相同记录只写一次：记录编号与摘要都相同，无论主节点还是更正段都沿用原节点。
        for node in sorted(dataset["nodes"], key=lambda item: int(item.get("台账序号") or 0)):
            if node.get("记录编号") == record["记录编号"] and node.get("记录摘要") == digest:
                return (
                    {
                        "节点编号": node["节点编号"],
                        "记录摘要": digest,
                        "写入结果": "重复写入未追加",
                        "去重": True,
                        "主节点数": len(mains),
                        "更正段数": len(correction_nodes(dataset["nodes"])),
                    },
                    f"{record['记录编号']} 与已归档记录完全一致，沿用 {node['节点编号']}，未追加新节点",
                    {"deduped": True, "node": node},
                )

        node_id = max((int(node.get("id", 0)) for node in dataset["nodes"]), default=0) + 1
        ledger_seq = max((int(node.get("台账序号", 0)) for node in dataset["nodes"]), default=0) + 1
        tail = mains[-1] if mains else None
        original = next((node for node in mains if node.get("记录编号") == record["记录编号"]), None)
        late = tail is not None and request_time < str(tail.get("请求时间") or "")
        adjudication: dict[str, Any] | None = None
        queue_item: dict[str, Any] | None = None

        if original is not None:
            # 2) 同一条记录的新内容：作为更正段锚定原主节点，绝不新增主节点。
            if late:
                reason = (
                    f"归档末尾为 {tail['请求时间']}，收到 {record['请求时间']} 的迟到更正，"
                    f"原节点 {original['节点编号']} 保留，更正另立段落"
                )
                conflict_type = "迟到更正"
            else:
                reason = (
                    f"记录 {record['记录编号']} 已归档为 {original['节点编号']}，"
                    f"本次内容不同，按更正段落追加，主节点保持唯一"
                )
                conflict_type = "记录更正"
            adjudication = self._open_conflict(
                dataset,
                record=record,
                digest=digest,
                original=original,
                conflict_type=conflict_type,
                reason=reason,
            )
            queue_item = self._enqueue_breakpoint(
                dataset,
                queue_sink=queue_sink,
                record=record,
                digest=digest,
                reason=adjudication["冲突说明"],
                adjudication=adjudication,
                queue_type="摘要断点",
            )
            node = build_correction_node(
                node_id=node_id,
                ledger_seq=ledger_seq,
                dataset_code=dataset["数据集编号"],
                record=record,
                original=original,
                reason=adjudication["冲突说明"],
                queue_code=queue_item["队列编号"],
                conflict_code=adjudication["裁决编号"],
                written_at=_now(),
            )
            result_kind = "更正段已锚定原节点"
        else:
            node = build_main_node(
                node_id=node_id,
                ledger_seq=ledger_seq,
                dataset_code=dataset["数据集编号"],
                record=record,
                seq=len(mains) + 1,
                prev_chain=str(tail.get("链摘要") or GENESIS) if tail else GENESIS,
                written_at=_now(),
            )
            if late:
                # 3) 新记录但请求时间早于归档末尾：主链只追加，标记顺序异常并交裁决。
                adjudication = self._open_conflict(
                    dataset,
                    record=record,
                    digest=digest,
                    original=tail,
                    conflict_type="迟到日志",
                    reason=(
                        f"归档末尾为 {tail['请求时间']}，迟到日志请求时间为 {record['请求时间']}，"
                        f"按追加顺序写入主链第 {node['主链序号']} 位并标记顺序异常"
                    ),
                )
                queue_item = self._enqueue_breakpoint(
                    dataset,
                    queue_sink=queue_sink,
                    record=record,
                    digest=digest,
                    reason=adjudication["冲突说明"],
                    adjudication=adjudication,
                    queue_type="顺序异常",
                )
                node["顺序异常"] = True
                node["断点"] = True
                node["断点原因"] = adjudication["冲突说明"]
                node["队列编号"] = queue_item["队列编号"]
                node["裁决编号"] = adjudication["裁决编号"]
                result_kind = "迟到日志按追加顺序写入"
            else:
                result_kind = "新建主节点"

        node["摘要指纹"] = full
        dataset["nodes"].append(node)
        if adjudication is not None:
            adjudication["节点编号"] = node["节点编号"]
        if queue_item is not None:
            queue_item["节点编号"] = node["节点编号"]
            queue_item["节点类型"] = node["节点类型"]
        self._refresh(dataset)

        if result_kind == "新建主节点":
            message = f"{record['记录编号']} 已写入主链，序号 {node['主链序号']}"
        elif result_kind == "迟到日志按追加顺序写入":
            message = f"{record['记录编号']} 为迟到日志，已追加到主链第 {node['主链序号']} 位并登记裁决 {adjudication['裁决编号']}"
        else:
            message = (
                f"{record['记录编号']} 已生成更正段 {node['节点编号']}，"
                f"仍指向原节点 {original['节点编号']}，登记裁决 {adjudication['裁决编号']}"
            )
        result = {
            "节点编号": node["节点编号"],
            "节点类型": node["节点类型"],
            "主链序号": node.get("主链序号"),
            "记录摘要": digest,
            "写入结果": result_kind,
            "去重": False,
            "主节点数": int(dataset["主节点数"]),
            "更正段数": int(dataset["更正段数"]),
            "裁决编号": adjudication["裁决编号"] if adjudication else None,
            "队列编号": queue_item["队列编号"] if queue_item else None,
            "链摘要": node["链摘要"],
        }
        return result, message, {
            "deduped": False,
            "node": node,
            "adjudication": adjudication,
            "queue": queue_item,
        }

    # ------------------------------------------------------------------ 校验与导出
    def verify(self, dataset_id: int) -> dict[str, Any]:
        dataset = store.find(MODULE, dataset_id)
        if dataset is None:
            return {"ok": False, "message": f"日志审计数据集 {dataset_id} 不存在", "checks": []}
        return self._verify_dataset(dataset)

    def _verify_dataset(self, dataset: dict[str, Any]) -> dict[str, Any]:
        nodes = dataset.get("nodes") or []
        mains = main_nodes(nodes)
        corrections = correction_nodes(nodes)
        checks: list[dict[str, Any]] = []
        prev = GENESIS
        chain_ok = True
        for index, node in enumerate(mains, start=1):
            expected = chain_digest(
                main_seq_label(index),
                prev,
                str(node.get("记录摘要") or ""),
                str(node.get("记录编号") or ""),
                str(node.get("请求时间") or ""),
            )
            if (
                int(node.get("主链序号") or 0) != index
                or node.get("前序摘要") != prev
                or node.get("链摘要") != expected
            ):
                chain_ok = False
            prev = str(node.get("链摘要") or "")
        checks.append({
            "名称": "主链摘要可重算",
            "通过": chain_ok,
            "说明": "逐条按前序摘要与记录摘要重算，全部与归档值一致" if chain_ok else "存在无法重算的链节点",
        })
        seq_ok = [int(node.get("主链序号") or 0) for node in mains] == list(range(1, len(mains) + 1))
        checks.append({
            "名称": "主链序号连续",
            "通过": seq_ok,
            "说明": f"主链 1-{len(mains)} 连续无缺口" if seq_ok else "主链序号存在缺口或重复",
        })
        numbers = [node.get("记录编号") for node in mains]
        no_dup = len(numbers) == len(set(numbers))
        checks.append({
            "名称": "记录不重复",
            "通过": no_dup,
            "说明": "每个记录编号只有一条主节点" if no_dup else "存在重复记录写入",
        })
        ledger_keys = [
            (node.get("记录编号"), node.get("记录摘要")) for node in (dataset.get("nodes") or [])
        ]
        no_ledger_dup = len(ledger_keys) == len(set(ledger_keys))
        checks.append({
            "名称": "台账节点唯一",
            "通过": no_ledger_dup,
            "说明": "主节点与更正段的记录摘要都不重复" if no_ledger_dup else "台账中存在完全相同的节点",
        })
        count_ok = int(dataset.get("采集请求数") or 0) == len(mains)
        checks.append({
            "名称": "归档条数一致",
            "通过": count_ok,
            "说明": f"采集请求数 {dataset.get('采集请求数')} 与主节点数 {len(mains)} 一致",
        })
        anchors_ok = all(
            any(node.get("节点编号") == correction.get("归属节点") for node in mains)
            for correction in corrections
        )
        checks.append({
            "名称": "更正段可定位原记录",
            "通过": anchors_ok,
            "说明": "每条更正段都指向存在的主节点" if anchors_ok else "存在指向缺失节点的更正段",
        })
        tail_ok = (not mains) or dataset.get("尾链摘要") == mains[-1].get("链摘要")
        checks.append({
            "名称": "尾链摘要一致",
            "通过": bool(tail_ok),
            "说明": f"尾链摘要 {dataset.get('尾链摘要')}",
        })
        first_ok = (not mains) or dataset.get("首条时间") == mains[0].get("请求时间")
        checks.append({
            "名称": "首条时间一致",
            "通过": bool(first_ok),
            "说明": f"首条时间 {dataset.get('首条时间')}",
        })
        ok = all(check["通过"] for check in checks)
        return {
            "ok": ok,
            "message": "摘要链可验证" if ok else "摘要链校验未通过",
            "数据集编号": dataset.get("数据集编号"),
            "归档文件": dataset.get("归档文件"),
            "主节点数": len(mains),
            "更正段数": len(corrections),
            "尾链摘要": dataset.get("尾链摘要"),
            "摘要断点": self.breakpoints(dataset),
            "checks": checks,
        }

    def export_detail(self, dataset_id: int) -> dict[str, Any] | None:
        dataset = store.find(MODULE, dataset_id)
        if dataset is None:
            return None
        return self._export_dataset(dataset)

    def _export_dataset(self, dataset: dict[str, Any]) -> dict[str, Any]:
        nodes = dataset.get("nodes") or []
        rows = build_export_rows(nodes)
        verification = self._verify_dataset(dataset)
        return {
            "module": MODULE,
            "数据集编号": dataset.get("数据集编号"),
            "归档文件": dataset.get("归档文件"),
            "来源批次": dataset.get("来源批次"),
            "导出批次": f"EXP-{dataset.get('归档文件')}",
            "记录数": len(rows),
            "主节点数": int(dataset.get("主节点数") or 0),
            "更正段数": int(dataset.get("更正段数") or 0),
            "首条时间": rows[0]["请求时间"] if rows else None,
            "末条时间": rows[-1]["请求时间"] if rows else None,
            "尾链摘要": dataset.get("尾链摘要"),
            "摘要顺序": rows,
            "摘要断点": self.breakpoints(dataset),
            "校验": {
                "ok": verification["ok"],
                "message": verification["message"],
                "checks": verification["checks"],
            },
        }

    def breakpoints(self, dataset: dict[str, Any]) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        for node in sorted(dataset.get("nodes") or [], key=lambda item: int(item.get("台账序号") or 0)):
            if not node.get("断点"):
                continue
            points.append({
                "断点节点": node.get("节点编号"),
                "节点类型": node.get("节点类型"),
                "记录编号": node.get("记录编号"),
                "请求时间": node.get("请求时间"),
                "记录摘要": node.get("记录摘要"),
                "归属节点": node.get("归属节点"),
                "断点原因": node.get("断点原因"),
                "队列编号": node.get("队列编号"),
                "裁决编号": node.get("裁决编号"),
            })
        return points

    # ------------------------------------------------------------------ 动作与队列
    def run_action(
        self,
        dataset_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        dataset = store.find(MODULE, dataset_id)
        if dataset is None:
            return None, f"日志审计数据集 {dataset_id} 不存在"
        if action == "校验摘要链":
            verification = self._verify_dataset(dataset)
            return dataset, verification["message"]
        if action == "裁决冲突":
            return self._adjudicate(dataset, values)
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于日志审计数据集可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if action == "封存数据集":
            open_conflicts = [item for item in dataset.get("conflicts", []) if item.get("状态") == "待裁决"]
            if open_conflicts:
                return None, f"仍有 {len(open_conflicts)} 条冲突待裁决，暂不能封存"
        dataset["status"] = target
        dataset["pending"] = target != STATUS_ORDER[-1]
        dataset["abnormal"] = False
        return dataset, f"日志审计数据集已{action}"

    def _adjudicate(self, dataset: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        code = str(values.get("裁决编号") or "").strip()
        decision = str(values.get("裁决") or "保留原记录").strip()
        conflict = next(
            (item for item in dataset.get("conflicts", []) if item.get("裁决编号") == code),
            None,
        )
        if conflict is None:
            return None, f"裁决编号 {code or '（空）'} 不存在"
        if conflict.get("状态") != "待裁决":
            return None, f"裁决 {code} 已处理，不能重复裁决"
        conflict["状态"] = "已裁决"
        conflict["裁决"] = decision
        conflict["裁决时间"] = _now()
        remaining = [item for item in dataset.get("conflicts", []) if item.get("状态") == "待裁决"]
        if not remaining:
            dataset["abnormal"] = False
            if dataset.get("status") == "待裁决":
                dataset["status"] = "收集中"
            dataset["pending"] = dataset.get("status") != STATUS_ORDER[-1]
        return dataset, f"冲突 {code} 已裁决：{decision}；主链保持只追加，更正段仍锚定原节点"

    def list_queue(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(QUEUE_MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("队列编号", "")) or keyword in str(row.get("记录编号", ""))
                or keyword in str(row.get("归档文件", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_queue_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(QUEUE_MODULE, entry_id)

    def run_queue_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(QUEUE_MODULE, entry_id)
        if entry is None:
            return None, f"审计交付待处理队列项 {entry_id} 不存在"
        if action not in QUEUE_ACTIONS:
            return None, f"动作「{action}」不属于审计交付待处理队列可执行范围"
        target = QUEUE_ACTIONS[action]
        entry["status"] = target
        entry["pending"] = target == QUEUE_STATUS[0]
        entry["abnormal"] = False
        entry["处理时间"] = _now()
        return entry, f"队列项 {entry['队列编号']} 已{action}"

    # ------------------------------------------------------------------ 复测
    def recheck(self, dataset_id: int) -> dict[str, Any] | None:
        """在数据集副本上跑“重复写入 + 一条迟到更正”，不改动正式归档与交付队列。"""
        dataset = store.find(MODULE, dataset_id)
        if dataset is None:
            return None
        sandbox = copy.deepcopy(dataset)
        sandbox["nodes"] = []
        sandbox["conflicts"] = []
        # 复测在副本上进行：副本视为收集中，避免已封存状态挡住写入，正式归档不受影响。
        sandbox["status"] = STATUS_ORDER[0]
        queue_sink: list[dict[str, Any]] = []
        for node in dataset.get("nodes") or []:
            sandbox["nodes"].append(copy.deepcopy(node))
        self._refresh(sandbox)

        mains_before = len(main_nodes(sandbox["nodes"]))
        existing_corrections = {
            node.get("节点编号") for node in correction_nodes(sandbox["nodes"])
        }
        target = main_nodes(sandbox["nodes"])[0]
        duplicate = dict(target["记录内容"])
        _, duplicate_message, duplicate_extra = self._ingest_into(sandbox, duplicate, queue_sink=queue_sink)
        mains_after_duplicate = len(main_nodes(sandbox["nodes"]))

        late_record = dict(target["记录内容"])
        late_record["请求时间"] = "2026-11-15T07:58:00"
        # 复测要证明“迟到的不同更正会新立更正段”，因此挑一个档案里还没出现过的耗时，
        # 避免同一份复测连跑两次时被“相同记录只写一次”直接去重掉。
        used = {
            node.get("记录内容", {}).get("耗时毫秒")
            for node in sandbox["nodes"]
            if node.get("记录编号") == target["记录编号"]
        }
        latency = 1024
        while str(latency) in used:
            latency += 7
        late_record["耗时毫秒"] = str(latency)
        ingest_result, late_message, late_extra = self._ingest_into(
            sandbox, late_record, queue_sink=queue_sink
        )
        mains_after_correction = len(main_nodes(sandbox["nodes"]))
        corrections = [
            node for node in correction_nodes(sandbox["nodes"])
            if node.get("节点编号") not in existing_corrections
        ]
        correction = corrections[-1] if corrections else None
        export = self._export_dataset(sandbox)
        verification = self._verify_dataset(sandbox)

        first_time = str(target.get("请求时间") or "")
        digest_ok = (
            mains_after_duplicate == mains_before
            and mains_after_correction == mains_before
            and (
                target.get("记录编号") != "LOG-301"
                or target.get("记录摘要") == "H7K2"
            )
        )
        duplicate_ok = mains_after_duplicate == mains_before and duplicate_extra.get("deduped") is True
        correction_ok = (
            correction is not None
            and correction.get("归属节点") == target.get("节点编号")
            and mains_after_correction == mains_before
        )
        first_row = export["摘要顺序"][0] if export["摘要顺序"] else {}
        export_ok = (
            export["记录数"] == mains_before
            and export["首条时间"] == first_time
            and first_row.get("记录摘要") == target.get("记录摘要")
        )
        queue_ok = len(queue_sink) >= 1
        checks = [
            {
                "名称": "重复写入不追加主节点",
                "通过": duplicate_ok,
                "说明": f"重复写入 {target['记录编号']} 后主节点数保持 {mains_before}",
            },
            {
                "名称": "摘要链只有一个主节点",
                "通过": digest_ok,
                "说明": (
                    f"{target['记录编号']} 的主摘要为 {target.get('记录摘要')}，"
                    f"重复写入与迟到更正之后主节点数仍为 {mains_before}"
                ),
            },
            {
                "名称": "更正段定位原记录",
                "通过": correction_ok,
                "说明": (
                    f"更正段 {correction['节点编号']} 指向 {correction['归属节点']}"
                    if correction else "未生成更正段"
                ),
            },
            {
                "名称": "导出可逐项复核",
                "通过": export_ok,
                "说明": (
                    f"记录数 {export['记录数']}，首条时间 {export['首条时间']}，"
                    f"首条摘要 {first_row.get('记录摘要')}，顺序与归档一致"
                    if export["摘要顺序"] else "导出为空"
                ),
            },
            {
                "名称": "断点进入交付队列",
                "通过": queue_ok,
                "说明": f"副本队列中写入 {len(queue_sink)} 条摘要断点",
            },
            {
                "名称": "审计链可验证",
                "通过": verification["ok"],
                "说明": verification["message"],
            },
        ]
        ok = all(check["通过"] for check in checks)
        return {
            "ok": ok,
            "message": (
                "复测通过：摘要链只有一个主节点，迟到更正段仍能定位原记录"
                if ok else "复测未通过，请查看逐项校验"
            ),
            "数据集编号": dataset.get("数据集编号"),
            "归档文件": dataset.get("归档文件"),
            "记录数": mains_before,
            "主摘要": target.get("记录摘要"),
            "原节点": target.get("节点编号"),
            "重复写入": {
                "结果": duplicate_extra.get("node", {}).get("节点编号"),
                "说明": duplicate_message,
            },
            "迟到更正": {
                "结果": "更正段" if late_extra.get("node", {}).get("节点类型") == "更正段" else "主节点",
                "节点": late_extra.get("node", {}).get("节点编号"),
                "归属节点": late_extra.get("node", {}).get("归属节点"),
                "说明": late_message,
            },
            "导出": {
                "记录数": export["记录数"],
                "首条时间": export["首条时间"],
                "末条时间": export["末条时间"],
                "摘要断点数": len(export["摘要断点"]),
            },
            "checks": checks,
        }

    # ------------------------------------------------------------------ 内部
    def _refresh(self, dataset: dict[str, Any]) -> None:
        nodes = dataset.get("nodes") or []
        mains = main_nodes(nodes)
        dataset["主节点数"] = len(mains)
        dataset["更正段数"] = len(correction_nodes(nodes))
        dataset["采集请求数"] = len(mains)
        dataset["首条时间"] = mains[0]["请求时间"] if mains else None
        dataset["末条时间"] = mains[-1]["请求时间"] if mains else None
        dataset["尾链摘要"] = mains[-1]["链摘要"] if mains else GENESIS
        dataset["摘要断点数"] = len(self.breakpoints(dataset))
        dataset["pending"] = dataset.get("status") != STATUS_ORDER[-1] or dataset["摘要断点数"] > 0
        dataset["abnormal"] = any(
            item.get("状态") == "待裁决" for item in dataset.get("conflicts", [])
        )

    def _open_conflict(
        self,
        dataset: dict[str, Any],
        *,
        record: dict[str, str],
        digest: str,
        original: dict[str, Any] | None,
        conflict_type: str,
        reason: str,
    ) -> dict[str, Any]:
        dataset.setdefault("conflicts", [])
        seq = max((int(item.get("id", 0)) for item in dataset["conflicts"]), default=0) + 1
        conflict = {
            "id": seq,
            "裁决编号": f"ADJ-{dataset['id']:02d}{seq:03d}",
            "状态": "待裁决",
            "冲突类型": conflict_type,
            "记录编号": record["记录编号"],
            "记录摘要": digest,
            "请求时间": record["请求时间"],
            "冲突说明": reason,
            "原节点": original.get("节点编号") if original else None,
            "节点编号": None,
            "提交时间": _now(),
            "裁决": None,
        }
        dataset["conflicts"].append(conflict)
        dataset["status"] = "待裁决"
        dataset["pending"] = True
        dataset["abnormal"] = True
        return conflict

    def _enqueue_breakpoint(
        self,
        dataset: dict[str, Any],
        *,
        queue_sink: list[dict[str, Any]],
        record: dict[str, str],
        digest: str,
        reason: str,
        adjudication: dict[str, Any],
        queue_type: str,
    ) -> dict[str, Any]:
        entry_id = max((int(row.get("id", 0)) for row in queue_sink), default=0) + 1
        item = {
            "id": entry_id,
            "status": "待处理",
            "pending": True,
            "abnormal": False,
            "队列编号": f"Q-{entry_id:04d}",
            "数据集编号": dataset["数据集编号"],
            "归档文件": dataset["归档文件"],
            "类型": queue_type,
            "记录编号": record["记录编号"],
            "记录摘要": digest,
            "请求时间": record["请求时间"],
            "断点原因": reason,
            "裁决编号": adjudication["裁决编号"],
            "节点编号": None,
            "创建时间": _now(),
        }
        queue_sink.append(item)
        return item

    def _summary(self, dataset: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": dataset.get("id"),
            "status": dataset.get("status"),
            "pending": dataset.get("pending"),
            "abnormal": dataset.get("abnormal"),
            "数据集编号": dataset.get("数据集编号"),
            "归档文件": dataset.get("归档文件"),
            "来源批次": dataset.get("来源批次"),
            "采集请求数": dataset.get("采集请求数"),
            "主节点数": dataset.get("主节点数"),
            "更正段数": dataset.get("更正段数"),
            "摘要断点数": dataset.get("摘要断点数"),
            "首条时间": dataset.get("首条时间"),
            "末条时间": dataset.get("末条时间"),
            "尾链摘要": dataset.get("尾链摘要"),
            "建集时间": dataset.get("建集时间"),
        }


service = AuditService()
