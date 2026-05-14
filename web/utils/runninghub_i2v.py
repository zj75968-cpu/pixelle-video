"""RunningHub i2v 工作流参数发现与执行工具

把 web/pipelines/i2v.py 中 RunningHub 分支抽出，方便在其它页面（如「快速生成」）复用。

参数 UI 策略：按节点 class_type 查 schema 表（NODE_SCHEMAS），
精确映射每个云端工作流支持的可调字段、字段名（大小写敏感）与允许的值。
未在 schema 里的节点不会暴露任何参数 UI，避免传错字段触发 NODE_INFO_MISMATCH。
"""

from typing import Any
from loguru import logger


# 按节点 class_type 定义可暴露字段
# 每个字段：
#   field: 节点 inputs 里的真实字段名（大小写敏感）
#   type:  "enum_str" | "enum_int" | "int"
#   options: enum 时的固定候选；int 时可选 (min, max, step)
NODE_SCHEMAS: dict[str, list[dict[str, Any]]] = {
    "RH_Grok_Video3": [
        {"field": "aspect_ratio", "type": "enum_str",
         "options": ["2:3", "3:2", "1:1", "16:9", "9:16"]},
        {"field": "size", "type": "enum_str",
         "options": ["480P", "720P", "1080P"]},
        {"field": "duration_seconds", "type": "enum_int",
         "options": [3, 5, 6, 8, 10]},
        {"field": "seed", "type": "int",
         "min": 0, "max": 2**31 - 1, "step": 1},
    ],
}


async def discover_workflow_params(
    rh_client,
    workflow_id: str,
    workflow_config: dict | None = None,
) -> dict:
    """拉取云端工作流 JSON，按 NODE_SCHEMAS 暴露可调参数。

    workflow_config 可选，可在工作流 JSON 配置文件里显式指定：
        - image_node_id (str)
        - prompt_node_id (str)
        - prompt_field (str)
        - extra_params: [
              {"node_id", "field_name", "label", "type", "options"|"min"/"max"/"step"}
          ]
    显式映射优先于自动猜测，避免多 CR Text 工作流挑错节点。
    """
    cloud_workflow = await rh_client.get_workflow_json(workflow_id)

    cfg = workflow_config or {}
    image_node_id: str | None = cfg.get("image_node_id")
    prompt_node_id: str | None = cfg.get("prompt_node_id")
    prompt_field: str | None = cfg.get("prompt_field")
    params: list[dict] = []

    # 自动猜测（仅当配置未指定时）
    for nid, ndata in cloud_workflow.items():
        if not isinstance(ndata, dict):
            continue
        cls = ndata.get("class_type", "") or ""
        inputs = ndata.get("inputs", {}) or {}
        title = ""
        meta_obj = ndata.get("_meta")
        if isinstance(meta_obj, dict):
            title = meta_obj.get("title") or ""

        if image_node_id is None and cls in ("LoadImage", "LoadImageMask"):
            image_node_id = nid

        if prompt_node_id is None:
            for fname in ("prompt", "text", "positive"):
                if fname in inputs and not isinstance(inputs[fname], list):
                    prompt_node_id = nid
                    prompt_field = fname
                    break

        # schema 驱动的参数发现（按 class_type）
        schema = NODE_SCHEMAS.get(cls)
        if not schema:
            continue
        node_label = title or cls or f"node {nid}"
        for s in schema:
            fname = s["field"]
            ftype = s["type"]
            cur = inputs.get(fname)
            if nid == prompt_node_id and fname == prompt_field:
                continue
            if cur is None or isinstance(cur, list):
                continue

            entry: dict[str, Any] = {
                "node_id": nid,
                "field_name": fname,
                "current_value": cur,
                "label": f"{fname} ({node_label})",
            }
            if ftype == "enum_str":
                options = list(s.get("options", []))
                if cur not in options:
                    options.insert(0, cur)
                entry["inferred_type"] = "enum"
                entry["options"] = options
            elif ftype == "enum_int":
                try:
                    cur_int = int(cur)
                except Exception:
                    cur_int = cur
                options = list(s.get("options", []))
                if cur_int not in options:
                    options.insert(0, cur_int)
                entry["inferred_type"] = "enum"
                entry["options"] = options
                entry["current_value"] = cur_int
            elif ftype == "int":
                try:
                    cur_int = int(cur)
                except Exception:
                    cur_int = 0
                entry["inferred_type"] = "int"
                entry["current_value"] = cur_int
                entry["min"] = int(s.get("min", 0))
                entry["max"] = int(s.get("max", 2**31 - 1))
                entry["step"] = int(s.get("step", 1))
            else:
                continue
            params.append(entry)

    # 显式 extra_params（来自工作流配置文件）—— 完全覆盖自动猜测
    extra = cfg.get("extra_params") or []
    if extra:
        params = []  # 显式配置时不再叠加自动猜测的字段
        for p in extra:
            nid = p.get("node_id")
            fname = p.get("field_name") or p.get("field")  # 兼容两种键名
            if not nid or not fname:
                continue
            node = cloud_workflow.get(str(nid)) or {}
            cur = (node.get("inputs") or {}).get(fname)
            if isinstance(cur, list):
                cur = p.get("default")
            entry: dict[str, Any] = {
                "node_id": str(nid),
                "field_name": fname,
                "current_value": cur,
                "label": p.get("label") or f"{fname} (node {nid})",
            }
            ptype = p.get("type", "enum_str")
            if ptype == "enum_str":
                opts = list(p.get("options") or [])
                if cur is not None and cur not in opts:
                    opts.insert(0, cur)
                entry["inferred_type"] = "enum"
                entry["options"] = opts
            elif ptype == "enum_int":
                try:
                    cur_int = int(cur) if cur is not None else None
                except Exception:
                    cur_int = None
                opts = list(p.get("options") or [])
                if cur_int is not None and cur_int not in opts:
                    opts.insert(0, cur_int)
                entry["inferred_type"] = "enum"
                entry["options"] = opts
                entry["current_value"] = cur_int if cur_int is not None else (opts[0] if opts else 0)
                # 可选：选项显示文本（如把帧数 length 显示成"5s"），平行于 options
                disp = p.get("display_labels")
                if isinstance(disp, list) and len(disp) == len(p.get("options") or []):
                    # 注意：当 cur_int 不在 options 里被 insert 到首位时，需要补一项
                    if cur_int is not None and cur_int not in (p.get("options") or []):
                        disp = [str(cur_int)] + list(disp)
                    entry["display_labels"] = list(disp)
            elif ptype == "int":
                try:
                    cur_int = int(cur) if cur is not None else int(p.get("default", 0))
                except Exception:
                    cur_int = int(p.get("default", 0))
                entry["inferred_type"] = "int"
                entry["current_value"] = cur_int
                entry["min"] = int(p.get("min", 0))
                entry["max"] = int(p.get("max", 2**31 - 1))
                entry["step"] = int(p.get("step", 1))
            elif ptype == "str":
                entry["inferred_type"] = "str"
                entry["current_value"] = str(cur if cur is not None else p.get("default", ""))
            elif ptype == "bool":
                raw = cur if cur is not None else p.get("default", False)
                entry["inferred_type"] = "bool"
                entry["current_value"] = bool(raw)
            else:
                continue
            params.append(entry)

    return {
        "image_node_id": image_node_id,
        "prompt_node_id": prompt_node_id,
        "prompt_field": prompt_field,
        "params": params,
    }


async def run_runninghub_i2v(
    kit,
    workflow_id: str,
    image_path: str,
    prompt: str,
    param_overrides: list[tuple[str, str, Any]] | None = None,
    task_options: dict[str, Any] | None = None,
    workflow_config: dict | None = None,
    status_text=None,
) -> str | None:
    """执行 RunningHub i2v 工作流。

    task_options 支持的键（对应 RunningHub `/task/openapi/create` 高级接口）：
        - addMetadata (bool, 默认 True)
        - instanceType (str, 'default' 或 'plus')
        - usePersonalQueue (bool, 默认 False)
        - retainSeconds (int, 10~180)
        - accessPassword (str)
    """
    rh_executor = kit._get_runninghub_executor()
    rh_client = rh_executor.client

    if status_text is not None:
        status_text.text("正在上传图片到 RunningHub...")
    rh_filename = await rh_client.upload_file(image_path)
    logger.info(f"[i2v-runninghub] 图片已上传: {rh_filename}")

    discovery = await discover_workflow_params(rh_client, workflow_id, workflow_config)
    image_node_id = discovery["image_node_id"]
    prompt_node_id = discovery["prompt_node_id"]
    prompt_field = discovery["prompt_field"]

    if not image_node_id:
        raise Exception(f"云端工作流 {workflow_id} 中未找到 LoadImage 节点")
    if not prompt_node_id:
        raise Exception(f"云端工作流 {workflow_id} 中未找到提示词输入字段")

    node_info_list: list[dict] = [
        {"nodeId": image_node_id, "fieldName": "image", "fieldValue": rh_filename},
        {"nodeId": prompt_node_id, "fieldName": prompt_field, "fieldValue": prompt},
    ]

    if param_overrides:
        for node_id, field_name, value in param_overrides:
            if node_id == image_node_id and field_name == "image":
                continue
            if node_id == prompt_node_id and field_name == prompt_field:
                continue
            node_info_list.append({
                "nodeId": node_id,
                "fieldName": field_name,
                "fieldValue": value,
            })

    # 走原始 POST，支持 addMetadata / instanceType / usePersonalQueue / retainSeconds
    data: dict[str, Any] = {
        "apiKey": rh_client.api_key,
        "workflowId": workflow_id,
        "nodeInfoList": node_info_list,
    }
    options = task_options or {}
    if "addMetadata" in options and options["addMetadata"] is not None:
        data["addMetadata"] = bool(options["addMetadata"])
    inst = options.get("instanceType")
    if inst and inst != "default":
        data["instanceType"] = inst
    if options.get("usePersonalQueue"):
        data["usePersonalQueue"] = True
    rs = options.get("retainSeconds")
    if rs is not None and isinstance(rs, int) and rs > 0:
        data["retainSeconds"] = rs
    ap = options.get("accessPassword")
    if ap:
        data["accessPassword"] = ap

    logger.info(
        f"[i2v-runninghub] create_task workflow_id={workflow_id} "
        f"options={ {k: v for k, v in data.items() if k != 'apiKey'} }"
    )

    if status_text is not None:
        status_text.text("正在生成视频...")
    result = await rh_client._make_request("POST", "/task/openapi/create", data=data)
    task_data = result.get("data", {}) or {}
    task_id = task_data.get("taskId")
    if not task_id:
        raise Exception(f"RunningHub 任务创建失败: {result}")
    logger.info(f"[i2v-runninghub] task created: taskId={task_id}")

    video_result = await rh_executor._wait_for_task_completion(task_id, {})
    if video_result.status == "error":
        raise Exception(f"RunningHub 任务失败: {video_result.msg}")

    if video_result.videos:
        return video_result.videos[0]
    if video_result.outputs:
        for _nid, node_output in video_result.outputs.items():
            if isinstance(node_output, dict) and "videos" in node_output:
                vs = node_output["videos"]
                if vs:
                    return vs[0]
    return None


async def run_runninghub_i2v_v2(
    *,
    workflow_id: str,
    image_path: str | None,
    prompt: str,
    workflow_config: dict,
    named_image_paths: dict[str, str] | None = None,
    audio_path: str | None = None,
    param_overrides: list[tuple[str, str, Any]] | None = None,
    task_options: dict[str, Any] | None = None,
    status_text=None,
) -> str | None:
    """通过 OpenAPI v2 + 消费级 API Key 执行 ComfyUI workflow_id 形式的 i2v。

    与 :func:`run_runninghub_i2v` 的差异：
      - 不依赖 ComfyKit / runninghub_executor（v1 链路 + 企业级 key）。
      - 鉴权使用 ``config.comfyui.runninghub_consumer_api_key``。
      - 节点 ID/字段必须在 ``workflow_config`` 中显式声明，没有云端 JSON 拉取。

    workflow_config 必须包含：
        - ``image_node_id`` (str)：LoadImage 节点的 id
        - ``prompt_node_id`` (str)：CLIPTextEncode（或同类）节点的 id
        - ``prompt_field`` (str)：提示词字段名，常见 ``text``/``prompt``/``positive``
        可选：
        - ``image_field`` (str)：图片字段名，默认 ``image``
        - ``extra_params`` ：额外可调字段（同 v1 用法）

    Returns:
        视频 URL，或 None。
    """
    from pixelle_video.config import config_manager
    from pixelle_video.services.runninghub_v2 import RunningHubV2Client

    cfg = config_manager.get_comfyui_config()
    key = (cfg.get("runninghub_consumer_api_key") or "").strip()
    if not key:
        raise Exception(
            "未配置 `runninghub_consumer_api_key`（消费级 key），无法走 v2 路径。"
            "请在 config.yaml 的 comfyui.runninghub_consumer_api_key 填入或在「设置」页配置。"
        )
    base_url = (cfg.get("runninghub_base_url") or "").strip() or None
    public_base = (cfg.get("public_base_url") or "").strip()
    webhook_url = (
        f"{public_base.rstrip('/')}/webhooks/runninghub" if public_base else None
    )

    image_node_id = workflow_config.get("image_node_id")
    prompt_node_id = workflow_config.get("prompt_node_id")
    prompt_field = workflow_config.get("prompt_field") or "text"
    image_field = workflow_config.get("image_field") or "image"
    use_named = bool(named_image_paths)
    if not prompt_node_id:
        raise Exception("v2 路径要求 workflow JSON 显式声明 `prompt_node_id`。")
    if not use_named and not image_node_id:
        raise Exception(
            "v2 路径要求 workflow JSON 显式声明 `image_node_id`（或传入 named_image_paths）。"
        )

    # 从 image_inputs 构建 node_id -> field 映射
    input_field_map: dict[str, str] = {
        str(s["node_id"]): s.get("field", "image")
        for s in (workflow_config.get("image_inputs") or [])
    }

    client = RunningHubV2Client(api_key=key, base_url=base_url)

    node_info_list: list[dict] = []
    if use_named:
        # 多图槽位：逐一上传并注入对应节点
        for nid, img_path in named_image_paths.items():
            if not img_path:
                continue
            if status_text is not None:
                status_text.text(f"正在上传图片到 RunningHub（节点 {nid}）...")
            up = await client.upload_file(img_path)
            rh_fn = up.get("fileName") or up.get("download_url")
            if not rh_fn:
                raise Exception(f"v2 节点 {nid} 图片上传未返回 fileName: {up}")
            logger.info(f"[i2v-v2] 节点 {nid} 图片已上传: {rh_fn}")
            node_info_list.append({
                "nodeId": str(nid),
                "fieldName": input_field_map.get(str(nid), "image"),
                "fieldValue": rh_fn,
            })
    else:
        # 单图（原有逻辑）
        if status_text is not None:
            status_text.text("正在上传图片到 RunningHub (v2)...")
        up = await client.upload_file(image_path)
        rh_filename = up.get("fileName") or up.get("download_url")
        if not rh_filename:
            raise Exception(f"v2 上传未返回 fileName: {up}")
        logger.info(f"[i2v-v2] 图片已上传: {rh_filename}")
        node_info_list.append({
            "nodeId": str(image_node_id),
            "fieldName": image_field,
            "fieldValue": rh_filename,
        })

    node_info_list.append({"nodeId": str(prompt_node_id), "fieldName": prompt_field, "fieldValue": prompt})

    # 音频上传（如工作流配置了 audio_node_id）
    _audio_node_id = workflow_config.get("audio_node_id")
    _audio_field = workflow_config.get("audio_field") or "audio"
    if _audio_node_id and audio_path:
        if status_text is not None:
            status_text.text("正在上传音频到 RunningHub (v2)...")
        up_audio = await client.upload_file(audio_path)
        rh_audio_fn = up_audio.get("fileName") or up_audio.get("download_url")
        if not rh_audio_fn:
            raise Exception(f"v2 音频上传未返回 fileName: {up_audio}")
        logger.info(f"[i2v-v2] 音频已上传: {rh_audio_fn}")
        node_info_list.append({
            "nodeId": str(_audio_node_id),
            "fieldName": _audio_field,
            "fieldValue": rh_audio_fn,
        })

    # 可选：覆盖云端工作流中的负面提示词。
    # 某些模板把“静态/静止不动”写进负面词，容易导致生成视频动作很弱。
    neg_node_id = workflow_config.get("negative_node_id")
    neg_field = workflow_config.get("negative_field") or "text"
    neg_prompt = workflow_config.get("negative_prompt")
    if neg_node_id and isinstance(neg_prompt, str) and neg_prompt.strip():
        node_info_list.append({
            "nodeId": str(neg_node_id),
            "fieldName": str(neg_field),
            "fieldValue": neg_prompt.strip(),
        })
    if param_overrides:
        # 已注入的图片节点集合，避免 param_overrides 重复覆盖
        _injected_img_nodes = set(str(n) for n in (named_image_paths or {}).keys())
        if image_node_id:
            _injected_img_nodes.add(str(image_node_id))
        for node_id, field_name, value in param_overrides:
            if str(node_id) in _injected_img_nodes and field_name in (image_field, "image"):
                continue
            if str(node_id) == str(prompt_node_id) and field_name == prompt_field:
                continue
            node_info_list.append({
                "nodeId": str(node_id),
                "fieldName": field_name,
                "fieldValue": value,
            })

    options = task_options or {}
    # 打印实际下发到 RunningHub 的字段，方便排查"提示词没生效"等问题
    try:
        _safe_dump = [
            {**ni, "fieldValue": (
                (ni.get("fieldValue")[:80] + "…")
                if isinstance(ni.get("fieldValue"), str) and len(ni["fieldValue"]) > 80
                else ni.get("fieldValue")
            )}
            for ni in node_info_list
        ]
        logger.info(f"[i2v-v2] nodeInfoList -> {_safe_dump}")
    except Exception:
        pass
    try:
        create = await client.run_workflow(
            workflow_id=workflow_id,
            node_info_list=node_info_list,
            add_metadata=bool(options.get("addMetadata", True)),
            random_seed=options.get("randomSeed"),
            instance_type=options.get("instanceType") or "default",
            use_personal_queue=bool(options.get("usePersonalQueue", False)),
            retain_seconds=options.get("retainSeconds"),
            webhook_url=webhook_url,
        )
    except TypeError as e:
        # 兼容仍在运行的旧版本 client（未包含 random_seed 形参）
        if "unexpected keyword argument 'random_seed'" not in str(e):
            raise
        logger.warning("[i2v-v2] client 不支持 random_seed，回退旧调用签名")
        create = await client.run_workflow(
            workflow_id=workflow_id,
            node_info_list=node_info_list,
            add_metadata=bool(options.get("addMetadata", True)),
            instance_type=options.get("instanceType") or "default",
            use_personal_queue=bool(options.get("usePersonalQueue", False)),
            retain_seconds=options.get("retainSeconds"),
            webhook_url=webhook_url,
        )
    if create.get("code") not in (0, "0", None):
        raise Exception(f"v2 run_workflow 失败: {create}")
    task_id = create.get("taskId") or (create.get("data") or {}).get("taskId")
    if not task_id:
        raise Exception(f"v2 run_workflow 未返回 taskId: {create}")
    logger.info(
        f"[i2v-v2] task created taskId={task_id} workflow_id={workflow_id} "
        f"webhook={'on' if webhook_url else 'off'}"
    )

    if status_text is not None:
        status_text.text("正在生成视频 (v2)...")
    if webhook_url:
        final = await client.wait_via_webhook(task_id)
    else:
        final = await client.wait_for_task(task_id)
    if (final.get("status") or "").upper() != "SUCCESS":
        raise Exception(f"v2 任务未成功：{final}")

    results = final.get("results") or []
    for r in results:
        otype = (r.get("outputType") or "").lower()
        if otype in ("mp4", "webm", "mov"):
            return r.get("url")
    # 兜底：取首个带 url 的 result
    for r in results:
        if r.get("url"):
            return r["url"]
    return None
