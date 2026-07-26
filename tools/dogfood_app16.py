#!/usr/bin/env python3
"""APP-16 daily dogfood checklist against live local Cursor data.

Usage (from repo root, venv active):
  python tools/dogfood_app16.py
  python tools/dogfood_app16.py --json

Does not invent Auto GT. Uses real ~/.verkee/verify DB + CLI contracts.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional

REPO = Path(__file__).resolve().parents[1]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class DogfoodReport:
    date: str
    checks: List[Check] = field(default_factory=list)
    blocking: bool = False

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks) and not self.blocking


def _run(args: List[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _verkee_verify(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    exe = REPO / "venv" / "bin" / "verkee-verify"
    cmd = [str(exe) if exe.is_file() else "verkee-verify", *args]
    return _run(cmd, timeout=timeout)


def check_doctor() -> Check:
    r = _verkee_verify("cursor", "doctor", "--json")
    if r.returncode != 0:
        return Check("doctor", False, f"exit {r.returncode}: {r.stderr[:200]}")
    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return Check("doctor", False, f"invalid json: {e}")
    ok = bool(payload.get("ok"))
    warns = payload.get("warnings") or []
    detail = "ok" if ok else "failed"
    if warns:
        detail += f"; warnings={len(warns)}"
    return Check("doctor", ok, detail)


def check_latest_mix() -> Check:
    t0 = time.perf_counter()
    r = _verkee_verify("cursor", "task", "--latest", "--json")
    elapsed = time.perf_counter() - t0
    if r.returncode != 0:
        return Check("latest_json", False, f"exit {r.returncode}: {r.stderr[:200]}")
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return Check("latest_json", False, f"invalid json: {e}")
    mix = d.get("model_mix_v2") or {}
    models = mix.get("models") or {}
    if not models:
        return Check("latest_json", False, "model_mix_v2.models empty")
    pct_sum = sum(float(m.get("pct") or 0) for m in models.values())
    if abs(pct_sum - 100.0) > 0.5:
        return Check("latest_json", False, f"pct sum={pct_sum}")
    for key in ("factual_request_shares", "coverage", "inferred_request_shares"):
        if key not in d:
            return Check("latest_json", False, f"missing {key}")
    top = max(models.items(), key=lambda x: x[1].get("pct") or 0)
    detail = (
        f"{elapsed:.2f}s top={top[0]} {top[1].get('pct'):.0f}% "
        f"comp={mix.get('composition')} total={mix.get('total_calls')}"
    )
    # APP-16: answer "who most" within 5s
    ok = elapsed < 5.0
    return Check("latest_json", ok, detail)


def check_human_default() -> Check:
    r = _verkee_verify("cursor", "task", "--latest")
    if r.returncode != 0:
        return Check("human_default", False, f"exit {r.returncode}")
    out = r.stdout
    if "本会话模型构成" not in out:
        return Check("human_default", False, "missing 本会话模型构成")
    for bad in ("事实轨", "推断轨", "已确认"):
        if bad in out:
            return Check("human_default", False, f"default shows {bad}")
    return Check("human_default", True, "unified mix only")


def check_list_detail_parity() -> Check:
    r = _verkee_verify("cursor", "tasks", "--json")
    if r.returncode != 0:
        return Check("list_detail", False, f"tasks exit {r.returncode}")
    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return Check("list_detail", False, f"invalid json: {e}")
    tasks = payload if isinstance(payload, list) else payload.get("tasks") or []
    if not tasks:
        return Check("list_detail", False, "no tasks")
    mismatches = []
    checked = 0
    # Prefer sessions with subagents; fall back to first few
    ordered = sorted(tasks, key=lambda t: -(t.get("subagent_count") or 0))
    for t in ordered[:5]:
        tid = t["task_id"]
        dr = _verkee_verify("cursor", "task", tid, "--json")
        if dr.returncode != 0:
            mismatches.append(f"{tid[:8]}: detail exit {dr.returncode}")
            continue
        detail = json.loads(dr.stdout)
        mix = detail.get("model_mix_v2") or {}
        list_n = t.get("request_count")
        detail_n = detail.get("request_count")
        total = mix.get("total_calls")
        if list_n != detail_n or detail_n != total:
            mismatches.append(
                f"{tid[:8]}: list={list_n} detail={detail_n} mix={total}"
            )
        checked += 1
    if mismatches:
        return Check("list_detail", False, "; ".join(mismatches))
    return Check("list_detail", True, f"checked {checked} tasks list≡detail≡mix")


def check_npm_accept() -> Check:
    import os

    ext = REPO / "extensions" / "verai-cursor"
    ai = REPO / "venv" / "bin" / "verkee-verify"
    env = os.environ.copy()
    env["VERAI_AI_VERIFY_PATH"] = str(ai)
    r = subprocess.run(
        ["npm", "run", "accept"],
        cwd=str(ext),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if r.returncode != 0:
        return Check("npm_accept", False, (r.stderr or r.stdout)[-300:])
    # allow skipped import
    if "fail" in r.stdout and "fail 0" not in r.stdout:
        # node --test prints "fail 0"
        pass
    if re.search(r"ℹ fail [^0]", r.stdout) or "✖" in r.stdout:
        return Check("npm_accept", False, "test failures in output")
    return Check("npm_accept", True, "parity pass")


def run_dogfood() -> DogfoodReport:
    from datetime import date

    report = DogfoodReport(date=date.today().isoformat())
    for fn in (
        check_doctor,
        check_latest_mix,
        check_human_default,
        check_list_detail_parity,
        check_npm_accept,
    ):
        try:
            report.checks.append(fn())
        except Exception as e:  # noqa: BLE001 — dogfood must not crash
            report.checks.append(Check(fn.__name__, False, f"exception: {e}"))
    report.blocking = any(not c.ok for c in report.checks)
    return report


def to_markdown(report: DogfoodReport) -> str:
    lines = [
        f"## Dogfood 自动检查 — {report.date}",
        "",
        f"**结论：{'通过' if report.ok else '失败（有阻断）'}**",
        "",
        "| 检查项 | 结果 | 细节 |",
        "| --- | --- | --- |",
    ]
    for c in report.checks:
        lines.append(f"| {c.name} | {'Pass' if c.ok else 'Fail'} | {c.detail} |")
    lines.extend(
        [
            "",
            "口径：统一模型构成（非分轨）。数据源：本机真实 Cursor DB，非自造 Auto GT。",
            "",
            "命令：`python tools/dogfood_app16.py`",
        ]
    )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="APP-16 dogfood live checklist")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)
    report = run_dogfood()
    if args.json:
        print(
            json.dumps(
                {
                    "date": report.date,
                    "ok": report.ok,
                    "blocking": report.blocking,
                    "checks": [asdict(c) for c in report.checks],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(to_markdown(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
