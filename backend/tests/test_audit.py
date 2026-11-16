"""日志审计数据集回归测试：不依赖 pytest，直接 python -I 运行。

覆盖需求里的复测样例：LOG-301 主摘要 H7K2、ARC-55 含 128 条请求、
重复写入不追加节点、迟到更正另立更正段并指向原节点、导出逐项可复核。
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from app.audit import record_digest  # noqa: E402
from app.services.audit import service  # noqa: E402
from app.store import store  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        FAILURES.append(label)


def fresh() -> None:
    store.reset()


def test_seed_dataset() -> None:
    fresh()
    dataset = service.get_entry(1)
    assert dataset is not None
    check(dataset["归档文件"] == "ARC-55", "归档文件为 ARC-55", dataset["归档文件"])
    check(dataset["采集请求数"] == 128, "含 128 条请求", str(dataset["采集请求数"]))
    check(dataset["主节点数"] == 128, "主节点数为 128", str(dataset["主节点数"]))
    first = dataset["nodes"][0]
    check(first["记录编号"] == "LOG-301", "首条为 LOG-301", first["记录编号"])
    check(first["记录摘要"] == "H7K2", "LOG-301 主摘要为 H7K2", first["记录摘要"])
    check(dataset["首条时间"] == "2026-11-15T08:00:19", "首条时间一致", str(dataset["首条时间"]))
    check(dataset["校验"]["ok"], "示例归档摘要链可验证", dataset["校验"]["message"])


def test_duplicate_write() -> None:
    fresh()
    record = dict(service.get_entry(1)["nodes"][0]["记录内容"])
    before = service.get_entry(1)["主节点数"]
    result, message, _ = service.ingest(1, record)
    after = service.get_entry(1)["主节点数"]
    check(result is not None and result["去重"] is True, "重复写入被识别", message)
    check(before == after == 128, "重复写入不追加主节点", f"{before} -> {after}")
    # 时间写法不同但语义相同，也应视为同一条记录
    same = dict(record, 请求时间="2026-11-15 08:00:19")
    result2, message2, _ = service.ingest(1, same)
    check(result2 is not None and result2["去重"] is True, "时间格式归一后仍判重", message2)


def test_late_correction() -> None:
    fresh()
    original = service.get_entry(1)["nodes"][0]
    late = dict(original["记录内容"])
    late["请求时间"] = "2026-11-15T07:58:00"
    late["耗时毫秒"] = "1024"
    result, message, extra = service.ingest(1, late)
    dataset = service.get_entry(1)
    correction = [node for node in dataset["nodes"] if node["节点类型"] == "更正段"]
    check(len(correction) == 1, "迟到更正生成一段更正段", message)
    check(dataset["主节点数"] == 128, "主节点数仍为 128", str(dataset["主节点数"]))
    check(correction[0]["归属节点"] == original["节点编号"], "更正段指向原节点", correction[0]["归属节点"])
    check(result is not None and result["记录摘要"] != "H7K2", "更正段摘要是新摘要", str(result and result["记录摘要"]))
    check(dataset["摘要断点数"] == 1, "摘要断点数为 1", str(dataset["摘要断点数"]))
    queue = store.rows("auditqueue")
    check(len(queue) == 1 and queue[0]["记录编号"] == "LOG-301", "断点进入交付待处理队列", str(len(queue)))
    check(dataset["校验"]["ok"], "写入更正段后链仍可验证", dataset["校验"]["message"])
    # 同一条更正重复提交不再追加
    result3, _, _ = service.ingest(1, late)
    check(result3 is not None and result3["去重"] is True, "重复更正不追加", "第二次提交沿用原更正段")
    check(len([n for n in service.get_entry(1)["nodes"] if n["节点类型"] == "更正段"]) == 1, "更正段仍只有一段")


def test_late_main_record() -> None:
    fresh()
    values = {
        "记录编号": "LOG-999",
        "关联端点": "ENDP-0002",
        "请求时间": "2026-11-15T07:00:00",
        "响应状态": "200",
        "耗时毫秒": "150",
        "返回行数": "12",
        "错误信息": "",
        "重试次数": "0",
    }
    result, message, extra = service.ingest(1, values)
    dataset = service.get_entry(1)
    check(result is not None and result["主链序号"] == 129, "迟到新日志按追加顺序写入主链末位", message)
    node = extra["node"]
    check(node["顺序异常"] is True and node["断点"] is True, "迟到日志标记顺序异常", str(node["断点原因"]))
    check(dataset["主节点数"] == 129, "主节点数增加 1", str(dataset["主节点数"]))
    check(dataset["status"] == "待裁决", "数据集进入待裁决", dataset["status"])
    check(len(store.rows("auditqueue")) == 1, "顺序异常进入交付队列", str(len(store.rows("auditqueue"))))
    check(dataset["校验"]["ok"], "迟到日志写入后链仍可验证", dataset["校验"]["message"])
    conflict = dataset["conflicts"][0]["裁决编号"]
    entry, blocked = service.run_action(1, "封存数据集", {})
    check(entry is None, "有未裁决冲突时不能封存", blocked)
    entry, adjudicated = service.run_action(1, "裁决冲突", {"裁决编号": conflict, "裁决": "保留追加顺序"})
    check(entry is not None, "冲突可以裁决", adjudicated)
    entry, sealed = service.run_action(1, "封存数据集", {})
    check(entry is not None and entry["status"] == "已封存", "裁决后可封存", sealed)
    entry, again = service.run_action(1, "裁决冲突", {"裁决编号": conflict, "裁决": "重复裁决"})
    check(entry is None, "同一裁决不能重复执行", again)


def test_export_detail() -> None:
    fresh()
    detail = service.export_detail(1)
    assert detail is not None
    rows = detail["摘要顺序"]
    check(detail["记录数"] == 128, "导出记录数 128", str(detail["记录数"]))
    check(len(rows) == 128, "摘要顺序逐条对应", str(len(rows)))
    check(rows[0]["记录摘要"] == "H7K2", "首条摘要 H7K2", rows[0]["记录摘要"])
    check(detail["首条时间"] == "2026-11-15T08:00:19", "首条时间 08:00:19", str(detail["首条时间"]))
    check([row["序号"] for row in rows] == list(range(1, 129)), "导出顺序与主链一致", "1..128")
    times = [row["请求时间"] for row in rows]
    check(times == sorted(times), "示例归档按请求时间升序", "无乱序")
    check(all(row["记录摘要"] and row["链摘要"] for row in rows), "每条都带摘要与链摘要", "")
    # 断点同步
    original = dict(service.get_entry(1)["nodes"][0]["记录内容"])
    late = dict(original, 请求时间="2026-11-15T07:58:00", 耗时毫秒="1024")
    service.ingest(1, original)
    service.ingest(1, late)
    detail2 = service.export_detail(1)
    assert detail2 is not None
    check(detail2["记录数"] == 128, "更正段不影响导出行数", str(detail2["记录数"]))
    check(len(detail2["摘要断点"]) == 1, "导出详情列出摘要断点", str(len(detail2["摘要断点"])))
    check(detail2["摘要断点"][0]["记录编号"] == "LOG-301", "断点指向 LOG-301", detail2["摘要断点"][0]["记录编号"])


def test_tamper_detected() -> None:
    fresh()
    # get_entry 返回副本，篡改要直接落在仓库里才能验证链能发现改动
    store.rows("audit")[0]["nodes"][5]["记录摘要"] = "ZZZZ"
    check(not service.verify(1)["ok"], "篡改记录摘要后校验失败", "链摘要无法重算")


def test_recheck_api() -> None:
    fresh()
    result = service.recheck(1)
    assert result is not None
    check(result["ok"], "复测接口通过", result["message"])
    check(result["主摘要"] == "H7K2", "复测确认主摘要 H7K2", result["主摘要"])
    check(result["迟到更正"]["结果"] == "更正段", "复测迟到记录形成更正段", str(result["迟到更正"]))
    check(result["迟到更正"]["归属节点"] == "N-0001", "复测更正段指向 N-0001", str(result["迟到更正"]))
    check(result["导出"]["记录数"] == 128, "复测导出记录数 128", str(result["导出"]["记录数"]))
    check(result["导出"]["首条时间"] == "2026-11-15T08:00:19", "复测导出首条时间", str(result["导出"]["首条时间"]))
    # 复测不改动正式归档
    dataset = service.get_entry(1)
    check(dataset["更正段数"] == 0 and dataset["摘要断点数"] == 0, "复测不污染正式归档", "正式数据集无变更")
    check(len(store.rows("auditqueue")) == 0, "复测不污染交付队列", "队列为空")
    # 连跑两次结果一致
    second = service.recheck(1)
    assert second is not None
    check(second["ok"], "复测可重复执行", second["message"])


def test_new_dataset_from_batch() -> None:
    fresh()
    entry, missing = service.create_entry({
        "归档文件": "ARC-56",
        "来源批次": "BATCH-ARC-56",
        "记录列表": [
            {"记录编号": "LOG-401", "关联端点": "ENDP-0001", "请求时间": "2026-11-16T09:00:00"},
            {"记录编号": "LOG-402", "关联端点": "ENDP-0002", "请求时间": "2026-11-16T09:00:05"},
            {"记录编号": "LOG-401", "关联端点": "ENDP-0001", "请求时间": "2026-11-16T09:00:00"},
        ],
    })
    check(entry is not None and not missing, "按批次建集成功", entry["数据集编号"] if entry else "")
    assert entry is not None
    check(entry["主节点数"] == 2, "批次内重复记录只写一次", str(entry["主节点数"]))
    check(entry["采集请求数"] == 2, "采集请求数与主节点数一致", str(entry["采集请求数"]))
    verification = service.verify(entry["id"])
    check(verification["ok"], "新数据集链可验证", verification["message"])
    export = service.export_detail(entry["id"])
    assert export is not None
    check(export["记录数"] == 2 and export["首条时间"] == "2026-11-16T09:00:00", "新数据集导出可复核", str(export["记录数"]))


def test_required_fields() -> None:
    fresh()
    result, message, _ = service.ingest(1, {"记录编号": "LOG-500"})
    check(result is None and "缺少必填字段" in message, "缺字段拒绝写入", message)
    result, message, _ = service.ingest(1, {
        "记录编号": "LOG-501",
        "关联端点": "ENDP-0001",
        "请求时间": "昨天下午",
    })
    check(result is None and "无法识别" in message, "非法时间拒绝写入", message)


def main() -> int:
    tests = [
        test_seed_dataset,
        test_duplicate_write,
        test_late_correction,
        test_late_main_record,
        test_export_detail,
        test_tamper_detected,
        test_recheck_api,
        test_new_dataset_from_batch,
        test_required_fields,
    ]
    for test in tests:
        print(f"\n== {test.__name__} ==")
        test()
    print()
    if FAILURES:
        print(f"共 {len(FAILURES)} 项失败：{'、'.join(FAILURES)}")
        return 1
    print("全部用例通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
