"""Read local evidence and write a content-free inventory; never runs a model.

Run from any directory: python3 scripts/audit_experiment_history.py
Counts are archived attempts, not independent samples or publication metrics.
"""
from pathlib import Path
import collections
import csv
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/zh-CN/experiment_audit"
SOURCES = [
    "docs/doc", "experiments/appworld", ".metamorph/runs",
    "benchmarks/workbench/metamorph_runs",
    "benchmarks/workbench/metamorph_matrix_runs",
    "benchmarks/browsecomp-plus/runs",
    "benchmarks/tau2-bench/data/simulations",
]
MARKERS = ["APIConnectionError", "invalid_contract", "budget exhausted",
           "replay_contamination", "Traceback", "NOT_VERIFIED"]


def write_csv(name, rows, fields):
    with (OUT / name).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = set()
    for source in SOURCES:
        files.update(p for p in (ROOT / source).rglob("*") if p.is_file())
    files.update((ROOT / "docs/zh-CN").glob("*.md"))
    files.update((ROOT / "docs").glob("*.md"))
    files.update(ROOT.glob("server*.log"))
    # Exclude this audit's derived report from its own input manifest.
    files.discard(ROOT / "docs/zh-CN/EXPERIMENT_HISTORY.md")
    inventory, results, issues = [], [], []
    roots = collections.defaultdict(list)
    for p in sorted(files):
        rel = p.relative_to(ROOT).as_posix()
        raw = p.read_bytes()
        row = dict(path=rel, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                   format=p.suffix, records="", parse_status="binary", **{m: "" for m in MARKERS})
        data = None
        if p.suffix in {".json", ".jsonl", ".log", ".md", ".csv", ".txt"}:
            content = raw.decode("utf-8", errors="replace")
            row.update(parse_status="text", **{m: content.count(m) for m in MARKERS})
            try:
                if p.suffix == ".json":
                    data = json.loads(content)
                    row.update(parse_status="ok", records=1)
                elif p.suffix == ".jsonl":
                    lines = [line for line in content.splitlines() if line.strip()]
                    for line in lines:
                        json.loads(line)
                    row.update(parse_status="ok", records=len(lines))
                elif p.suffix == ".csv":
                    rows = list(csv.reader(content.splitlines()))
                    row.update(parse_status="ok", records=max(0, len(rows) - 1))
                    for i, r in enumerate(rows[1:], 2):
                        if len(r) != len(rows[0]):
                            issues.append(dict(path=rel, issue=f"CSV line {i}: {len(r)} columns; expected {len(rows[0])}"))
                            row["parse_status"] = "column_mismatch"
            except (ValueError, csv.Error) as e:
                row["parse_status"] = "invalid"
                issues.append(dict(path=rel, issue=f"{type(e).__name__}: parse failure (content omitted)"))
        inventory.append(row)
        if p.name == "result.json" and isinstance(data, dict):
            d = data
            metrics = d.get("budget") or d.get("metrics") or {}
            group = (rel.split("/runs/")[1].split("/")[0]
                     if rel.startswith("experiments/appworld/runs/") else
                     "workbench_matrix/" + str(d.get("condition"))
                     if "metamorph_matrix_runs" in rel else
                     "workbench_smoke" if "metamorph_runs" in rel else "local_runtime")
            r = dict(path=rel, group=group, task_id=d.get("task_id", d.get("task_index", "")),
                     domain=d.get("domain", ""), condition=d.get("condition", ""), seed=d.get("seed", ""),
                     status=d.get("status", "unknown"), protocol_valid=d.get("protocol_valid", "unknown"),
                     strict_success=d.get("strict_success", "unknown"),
                     official_correct=d.get("official_score", {}).get("correct", "unknown"),
                     total_tokens=d.get("total_tokens", metrics.get("total_tokens", "unknown")),
                     tool_calls=d.get("tool_calls", metrics.get("tool_calls", "unknown")),
                     latency_seconds=d.get("latency_seconds", metrics.get("wall_latency_seconds", metrics.get("latency_seconds", "unknown"))),
                     failure_category=d.get("failure_category") or "",
                     protocol_invalid_reasons=json.dumps(d.get("protocol_invalid_reasons", []), ensure_ascii=False))
            results.append(r)
            roots[group].append(r)
    write_csv("file_inventory.csv", inventory, list(inventory[0]))
    write_csv("result_index.csv", results, list(results[0]))
    write_csv("integrity_issues.csv", issues, ["path", "issue"])
    lines = ["# 本地实验产物盘点（自动生成）", "",
             "运行 `python3 scripts/audit_experiment_history.py` 更新。仅清点本机现存证据，不调用模型。",
             "所有数量均按结果文件计数，包含调试、失败、重复尝试；不可解释为独立样本或合并成功率。",
             "unknown 表示源字段缺失；没有补零或追认旧协议有效性。关键词次数仅作定位，不等于错误事件数。", "",
             f"纳入 {len(inventory)} 个文件，{len(results)} 个 result.json，{len(issues)} 项格式异常。", "",
             "| 输出根 / 组 | 结果文件 | completed | 协议有效 true / false / unknown | 官方成功文件数 |", "|---|---:|---:|---|---:|"]
    for group, rs in sorted(roots.items()):
        valid = collections.Counter(str(r["protocol_valid"]) for r in rs)
        success = sum(r["strict_success"] is True or r["official_correct"] is True for r in rs)
        lines.append(f"| {group} | {len(rs)} | {sum(r['status'] == 'completed' for r in rs)} | {valid['True']} / {valid['False']} / {valid['unknown']} | {success} |")
    lines += ["", "## AppWorld 没有单臂 result.json 的目录", "",
              "这些目录可能仅含 manifest、中断痕迹或独立 provider 微测试，不能计作完成的 benchmark arm。", ""]
    for p in sorted((ROOT / "experiments/appworld/runs").iterdir()):
        if p.is_dir() and not any(p.rglob("result.json")):
            lines.append(f"- `{p.name}`（现存文件 {sum(q.is_file() for q in p.rglob('*'))} 个）")
    lines += ["", "## 文件格式异常", ""]
    lines += [f"- `{r['path']}`：{r['issue']}" for r in issues] or ["无。"]
    lines += ["", "## 覆盖范围", "", *[f"- `{s}`" for s in SOURCES],
              "- docs 顶层及 docs/zh-CN 顶层 Markdown；server*.log。",
              "- 二进制 checkpoint 等仅记录字节数与 SHA-256；JSON/JSONL 全文解析，文本日志全文扫描。",
              "- 不扫描第三方源代码/自带测试日志、虚拟环境、下载数据集、缓存或 Git 内部日志。",
              "- 不导出原始对话、工具返回或凭据；本清单不是完整实验数据备份。", ""]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(dict(files=len(inventory), results=len(results), issues=issues), ensure_ascii=False))


if __name__ == "__main__":
    main()
