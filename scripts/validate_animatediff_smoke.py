# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""AnimateDiff smoke validation for local ComfyUI.

This script performs a one-command acceptance check after models are placed:
1) service reachability
2) required node visibility
3) required model availability
4) minimal prompt submission (optional)
5) standardized pass/fail report
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_WORKFLOW = Path("workflows/selfhost/video_animatediff_sd15.json")
DEFAULT_MODEL_ROOTS = [Path("C:/ComfyUI/models"), Path("D:/ComfyUI-Data/models")]


@dataclass
class CheckResult:
    service_ok: bool
    missing_nodes: list[str]
    missing_models: list[str]


def no_proxy_opener() -> urllib.request.OpenerDirector:
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request_json(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    opener = no_proxy_opener()
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    with opener.open(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_prompt(base_url: str, payload: dict[str, Any], timeout: int = 60) -> tuple[str | None, dict[str, Any] | None]:
    opener = no_proxy_opener()
    req = urllib.request.Request(
        f"{base_url}/prompt",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener.open(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            return str(data.get("prompt_id")), None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        parsed["http_status"] = exc.code
        return None, parsed


def read_workflow(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def get_required_models(workflow: dict[str, Any]) -> dict[str, str]:
    required: dict[str, str] = {}
    for node in workflow.values():
        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs", {})
        if class_type == "CheckpointLoaderSimple":
            name = inputs.get("ckpt_name")
            if isinstance(name, str) and name:
                required["CheckpointLoaderSimple.ckpt_name"] = name
        if class_type == "ADE_AnimateDiffLoaderGen1":
            name = inputs.get("model_name")
            if isinstance(name, str) and name:
                required["ADE_AnimateDiffLoaderGen1.model_name"] = name
    return required


def get_required_options(object_info: dict[str, Any], node_key: str, field_key: str) -> list[str]:
    try:
        raw = object_info[node_key]["input"]["required"][field_key][0]
        if isinstance(raw, list):
            return [str(x) for x in raw]
    except Exception:
        return []
    return []


def check_service_and_nodes(base_url: str) -> tuple[CheckResult, dict[str, Any], dict[str, Any]]:
    stats = request_json(base_url, "GET", "/system_stats", timeout=10)
    object_info = request_json(base_url, "GET", "/object_info", timeout=30)

    service_ok = bool(stats.get("devices"))
    required_nodes = ["ADE_AnimateDiffLoaderGen1", "VHS_VideoCombine", "CheckpointLoaderSimple"]
    missing_nodes = [n for n in required_nodes if n not in object_info]

    return CheckResult(service_ok=service_ok, missing_nodes=missing_nodes, missing_models=[]), stats, object_info


def filesystem_probe(required_models: dict[str, str], roots: list[Path]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for model in required_models.values():
        model_hits: list[str] = []
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob(model):
                model_hits.append(str(path))
        hits[model] = model_hits
    return hits


def build_smoke_prompt(
    workflow: dict[str, Any],
    object_info: dict[str, Any],
    width: int,
    height: int,
    frames: int,
    fps: int,
    steps: int,
    seed: int,
) -> dict[str, Any]:
    prompt = copy.deepcopy(workflow)

    # Keep low load for a smoke run.
    if "2" in prompt and isinstance(prompt["2"].get("inputs", {}).get("value"), str):
        prompt["2"]["inputs"]["value"] = "simple motion, clean scene, smooth animation"
    if "5" in prompt:
        prompt["5"].setdefault("inputs", {})["value"] = width
    if "6" in prompt:
        prompt["6"].setdefault("inputs", {})["value"] = height
    if "7" in prompt:
        prompt["7"].setdefault("inputs", {})["value"] = fps
    if "8" in prompt:
        prompt["8"].setdefault("inputs", {})["value"] = frames

    if "11" in prompt:
        inputs = prompt["11"].setdefault("inputs", {})
        inputs["seed"] = seed
        inputs["steps"] = steps
        inputs["cfg"] = min(float(inputs.get("cfg", 7)), 6.5)

    # Some ADE versions require beta_schedule explicitly.
    ade_beta_opts = get_required_options(object_info, "ADE_AnimateDiffLoaderGen1", "beta_schedule")
    if "10" in prompt:
        inputs = prompt["10"].setdefault("inputs", {})
        if "beta_schedule" not in inputs:
            inputs["beta_schedule"] = ade_beta_opts[0] if ade_beta_opts else "autoselect"

    return prompt


def classify_failure(service_ok: bool, missing_nodes: list[str], missing_models: list[str], message: str) -> str:
    if not service_ok:
        return "service"
    if missing_nodes:
        return "node"
    if missing_models:
        return "model"

    lowered = message.lower()
    if "beta_schedule" in lowered or "required input is missing" in lowered:
        return "parameter"
    if ".safetensors" in lowered or ".ckpt" in lowered or "not in" in lowered:
        return "model"
    return "unknown"


def extract_missing_filenames(text: str) -> list[str]:
    seen: set[str] = set()
    for match in re.findall(r"[A-Za-z0-9._-]+\.(?:safetensors|ckpt)", text):
        seen.add(match)
    return sorted(seen)


def wait_history(base_url: str, prompt_id: str, timeout: int) -> tuple[str, dict[str, Any], list[str]]:
    start = time.time()
    while time.time() - start < timeout:
        hist = request_json(base_url, "GET", f"/history/{prompt_id}", timeout=60)
        if prompt_id in hist:
            item = hist[prompt_id]
            status = item.get("status", {})
            status_str = str(status.get("status_str", "unknown"))
            outputs = item.get("outputs", {})
            result_paths: list[str] = []
            for output in outputs.values():
                gifs = output.get("gifs") or []
                for gif in gifs:
                    fullpath = gif.get("fullpath")
                    if fullpath:
                        result_paths.append(str(fullpath))
            return status_str, item, result_paths
        time.sleep(3)
    return "timeout", {"error": "history timeout"}, []


def print_report(report: dict[str, Any]) -> None:
    print("=" * 72)
    print(f"STATUS: {report['result']['status']}")
    print(f"CLASSIFICATION: {report['result'].get('classification', '-')}")
    print(f"MODE: {report['mode']}")
    print(f"WORKFLOW: {report['workflow']}")
    print(f"COMFY_URL: {report['comfy_url']}")
    print("-" * 72)
    print(f"SERVICE_OK: {report['checks']['service_ok']}")
    print(f"MISSING_NODES: {report['checks']['missing_nodes'] or '[]'}")
    print(f"MISSING_MODELS: {report['checks']['missing_models'] or '[]'}")
    if report['result'].get('prompt_id'):
        print(f"PROMPT_ID: {report['result']['prompt_id']}")
    if report['result'].get('outputs'):
        print("OUTPUTS:")
        for p in report['result']['outputs']:
            print(f"  - {p}")
    if report['result'].get('missing_files_from_error'):
        print("MISSING_FILES_FROM_ERROR:")
        for name in report['result']['missing_files_from_error']:
            print(f"  - {name}")
    if report['result'].get('error_message'):
        print("ERROR_MESSAGE:")
        print(report['result']['error_message'])
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate local AnimateDiff workflow on ComfyUI.")
    parser.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    parser.add_argument("--workflow", default=str(DEFAULT_WORKFLOW))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true", help="Only check service/nodes/models. Do not submit prompt.")
    parser.add_argument("--width", type=int, default=384)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--seed", type=int, default=123456789)
    parser.add_argument("--report-file", default="", help="Optional path to save JSON report.")
    args = parser.parse_args()

    workflow_path = Path(args.workflow)
    if not workflow_path.exists():
        print(f"ERROR: workflow not found: {workflow_path}", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "mode": "dry-run" if args.dry_run else "normal",
        "workflow": str(workflow_path),
        "comfy_url": args.comfy_url,
        "checks": {},
        "result": {},
    }

    try:
        workflow = read_workflow(workflow_path)
        required_models = get_required_models(workflow)

        check_result, _stats, object_info = check_service_and_nodes(args.comfy_url)

        # Model availability from ComfyUI options first, then filesystem probes as extra evidence.
        missing_models: list[str] = []
        options_snapshot = {
            "CheckpointLoaderSimple.ckpt_name": get_required_options(object_info, "CheckpointLoaderSimple", "ckpt_name"),
            "ADE_AnimateDiffLoaderGen1.model_name": get_required_options(object_info, "ADE_AnimateDiffLoaderGen1", "model_name"),
        }
        for key, model_name in required_models.items():
            opts = options_snapshot.get(key, [])
            if opts and model_name not in opts:
                missing_models.append(model_name)

        check_result.missing_models = sorted(set(missing_models))
        fs_hits = filesystem_probe(required_models, DEFAULT_MODEL_ROOTS)

        report["checks"] = {
            "service_ok": check_result.service_ok,
            "missing_nodes": check_result.missing_nodes,
            "missing_models": check_result.missing_models,
            "required_models": required_models,
            "comfy_options_probe": {k: len(v) for k, v in options_snapshot.items()},
            "filesystem_hits": fs_hits,
        }

        if args.dry_run:
            status = "PASS" if (check_result.service_ok and not check_result.missing_nodes and not check_result.missing_models) else "FAIL"
            msg = "dry-run checks completed"
            report["result"] = {
                "status": status,
                "classification": "ok" if status == "PASS" else classify_failure(
                    check_result.service_ok,
                    check_result.missing_nodes,
                    check_result.missing_models,
                    msg,
                ),
                "error_message": "" if status == "PASS" else msg,
            }
            print_report(report)
            if args.report_file:
                Path(args.report_file).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0 if status == "PASS" else 1

        prompt = build_smoke_prompt(
            workflow=workflow,
            object_info=object_info,
            width=args.width,
            height=args.height,
            frames=args.frames,
            fps=args.fps,
            steps=args.steps,
            seed=args.seed,
        )

        payload = {"prompt": prompt, "client_id": str(uuid.uuid4())}
        prompt_id, submit_error = post_prompt(args.comfy_url, payload, timeout=60)

        if submit_error is not None:
            msg = json.dumps(submit_error, ensure_ascii=False)
            report["result"] = {
                "status": "FAIL",
                "classification": classify_failure(
                    check_result.service_ok,
                    check_result.missing_nodes,
                    check_result.missing_models,
                    msg,
                ),
                "prompt_id": None,
                "outputs": [],
                "error_message": msg,
                "missing_files_from_error": extract_missing_filenames(msg),
                "submit_error": submit_error,
            }
            print_report(report)
            if args.report_file:
                Path(args.report_file).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1

        assert prompt_id is not None
        status_str, history_item, outputs = wait_history(args.comfy_url, prompt_id, timeout=args.timeout)
        if status_str in {"completed", "success"}:
            report["result"] = {
                "status": "PASS",
                "classification": "ok",
                "prompt_id": prompt_id,
                "outputs": outputs,
                "error_message": "",
            }
            print_report(report)
            if args.report_file:
                Path(args.report_file).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0

        msg = json.dumps(history_item, ensure_ascii=False)
        report["result"] = {
            "status": "FAIL",
            "classification": classify_failure(
                check_result.service_ok,
                check_result.missing_nodes,
                check_result.missing_models,
                msg,
            ),
            "prompt_id": prompt_id,
            "outputs": outputs,
            "error_message": msg,
            "missing_files_from_error": extract_missing_filenames(msg),
            "history": history_item,
        }
        print_report(report)
        if args.report_file:
            Path(args.report_file).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    except Exception as exc:
        msg = str(exc)
        report["result"] = {
            "status": "FAIL",
            "classification": "service",
            "error_message": msg,
            "missing_files_from_error": extract_missing_filenames(msg),
        }
        print_report(report)
        if args.report_file:
            Path(args.report_file).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
