"""One-off rewrite: switch digital_human pipeline to call Humo workflow directly via v2."""
from pathlib import Path
import re

P = Path("web/pipelines/digital_human.py")
src = P.read_text(encoding="utf-8")

# --- Edit 1: switch second_workflow_path in runninghub config block ---
src = src.replace(
    '"second_workflow_path": "workflows/runninghub/digital_combination.json",',
    '"second_workflow_path": "workflows/runninghub/humo_digital.json",',
    1,
)

# --- Edit 2: add _generate_humo_video helper right after _rh_v2_upload ---
helper = '''

async def _generate_humo_video(
    *,
    workflow_id: str,
    character_path,
    goods_path,
    audio_path,
    prompt_text: str,
) -> str | None:
    """Drive the Humo single-step e-commerce digital-human workflow via openapi/v2.

    Node mapping (Humo \u7535\u5546\u5c55\u793a+\u8bed\u97f3 by Aiwood):
      - 4  LoadImage    -> character image
      - 25 LoadImage    -> goods image (falls back to character if missing)
      - 5  LoadAudio    -> TTS audio
      - 13 WanVideoTextEncode positive_prompt -> prompt / goods text

    Returns the result video URL on success, None when the consumer key is missing
    or the v2 task fails.
    """
    char_ref = await _rh_v2_upload(character_path)
    if not char_ref:
        return None
    goods_ref = None
    if goods_path:
        goods_ref = await _rh_v2_upload(goods_path)
    if not goods_ref:
        goods_ref = char_ref
    audio_ref = await _rh_v2_upload(audio_path)
    if not audio_ref:
        return None
    node_info_list = [
        {"nodeId": "4", "fieldName": "image", "fieldValue": char_ref},
        {"nodeId": "25", "fieldName": "image", "fieldValue": goods_ref},
        {"nodeId": "5", "fieldName": "audio", "fieldValue": audio_ref},
        {
            "nodeId": "13",
            "fieldName": "positive_prompt",
            "fieldValue": (prompt_text or "").strip(),
        },
    ]
    res = await _try_runninghub_v2(
        workflow_id=workflow_id,
        node_info_list=node_info_list,
        expected="video",
    )
    return res["url"] if res else None
'''
# Insert helper after the line ending of the `_rh_v2_upload` function
anchor = '    up = await client.upload_file(local_path)\n    return up.get("fileName") or up.get("download_url")\n'
assert src.count(anchor) == 1, f"anchor occurrences: {src.count(anchor)}"
src = src.replace(anchor, anchor + helper, 1)

# --- Edit 3: replace whole `async def generate_digital_human_video()` body ---
# We use regex to match from "try:" up to "# Execute async generation" (inclusive of the next line).
# Find the unique enclosing region: from `                start_time = time.time()` to `                    # Execute async generation`.
new_block = '''                start_time = time.time()
                
                try:
                    # Define async generation function
                    async def generate_digital_human_video():
                        import json
                        from pathlib import Path

                        task_dir, _task_id = create_task_output_dir()
                        logger.info(f"[digital_human] Task directory: {task_dir}")

                        # Resolve workflow file (must be runninghub source for Humo path).
                        # We bypass the legacy two-step pipeline and call the Humo workflow
                        # directly via openapi/v2 + consumer-tier API key.
                        workflow_path = video_params["workflow_path"]
                        second_workflow_path = Path(workflow_path.get("second_workflow_path"))
                        if not second_workflow_path.exists():
                            raise Exception(
                                f"Humo workflow file not found: {second_workflow_path}"
                            )
                        with open(second_workflow_path, "r", encoding="utf-8") as f:
                            second_workflow_config = json.load(f)
                        if not (
                            second_workflow_config.get("source") == "runninghub"
                            and "workflow_id" in second_workflow_config
                        ):
                            raise Exception(
                                "Humo workflow file is not a RunningHub workflow "
                                "(expect source=runninghub + workflow_id)."
                            )
                        workflow_id = str(second_workflow_config["workflow_id"])

                        # Decide TTS text + character/goods inputs based on UI mode.
                        product_prompt_local = (video_params.get("product_prompt") or "").strip()
                        if mode == "customize":
                            tts_text = (goods_text or "").strip()
                            char_path = character_assets[0]
                            goods_path = None  # no goods image in customize mode
                            prompt_text = tts_text
                        else:  # "digital"
                            tts_text = (
                                goods_text
                                or product_prompt_local
                                or goods_title
                                or ""
                            ).strip()
                            char_path = character_assets[0]
                            goods_path = goods_assets[0] if goods_assets else None
                            prompt_text = (
                                goods_text or product_prompt_local or goods_title or ""
                            ).strip()

                        if not tts_text:
                            raise Exception(
                                "No text content available for TTS. "
                                "Please fill in goods text / product prompt / goods title first."
                            )

                        # ---- Step 1: TTS ----
                        status_text.text(tr("progress.step_audio"))
                        progress_bar.progress(20)
                        audio_path = os.path.join(task_dir, "narration.mp3")
                        tts_inference_mode = video_params.get("tts_inference_mode", "local")
                        tts_kwargs = {
                            "text": tts_text,
                            "output_path": audio_path,
                            "inference_mode": tts_inference_mode,
                        }
                        if tts_inference_mode == "local":
                            tts_kwargs["voice"] = video_params.get("tts_voice")
                            tts_kwargs["speed"] = video_params.get("tts_speed")
                        elif tts_inference_mode == "comfyui":
                            tw = video_params.get("tts_workflow")
                            ra = video_params.get("ref_audio")
                            if tw:
                                tts_kwargs["workflow"] = tw
                            if ra:
                                tts_kwargs["ref_audio"] = ra
                        await pixelle_video.tts(**tts_kwargs)
                        progress_bar.progress(50)

                        # ---- Step 2: Humo single-step video synthesis ----
                        status_text.text(tr("progress.concatenating"))
                        logger.info(
                            f"[digital_human] invoking Humo workflow_id={workflow_id} "
                            f"mode={mode} char={char_path} goods={goods_path}"
                        )
                        generated_video_url = await _generate_humo_video(
                            workflow_id=workflow_id,
                            character_path=char_path,
                            goods_path=goods_path,
                            audio_path=audio_path,
                            prompt_text=prompt_text,
                        )
                        if not generated_video_url:
                            raise Exception(
                                "Humo workflow did not return a video. "
                                "Check [digital_human] / [rh-v2] logs."
                            )
                        logger.info(f"[digital_human] Humo OK: {generated_video_url}")

                        # ---- Step 3: download ----
                        final_video_path = os.path.join(task_dir, "final.mp4")
                        timeout = httpx.Timeout(300.0)
                        async with httpx.AsyncClient(timeout=timeout) as client:
                            response = await client.get(generated_video_url)
                            response.raise_for_status()
                            with open(final_video_path, "wb") as f:
                                f.write(response.content)
                        progress_bar.progress(100)
                        status_text.text(tr("status.success"))
                        return final_video_path

                    # Execute async generation'''

# We need to replace the region from `                start_time = time.time()` up to and INCLUDING
# `                    # Execute async generation` (the line just before `final_video_path = run_async(...)`).
# Use a regex with DOTALL.
pattern = re.compile(
    r"[ ]{16}start_time = time\.time\(\)\n.*?[ ]{20}# Execute async generation",
    re.DOTALL,
)
matches = pattern.findall(src)
assert len(matches) == 1, f"expected exactly one match, got {len(matches)}"
src = pattern.sub(new_block, src, count=1)

P.write_text(src, encoding="utf-8", newline="\n")
print("OK, new length:", len(src), "lines:", src.count("\n") + 1)
