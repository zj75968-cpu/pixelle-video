
import sys
import json

path = "web/pipelines/digital_human.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

start_marker = "if not second_workflow_path.exists():"
end_marker = "raise Exception(\"The second step of the workflow did not return a video. Please check the workflow configuration.\")"

def find_blocks(lines, start_m, end_m):
    blocks = []
    i = 0
    while i < len(lines):
        if start_m in lines[i]:
            start_idx = i
            while i < len(lines) and end_m not in lines[i]:
                i += 1
            if i < len(lines):
                blocks.append((start_idx, i))
        i += 1
    return blocks

blocks = find_blocks(lines, start_marker, end_marker)
if len(blocks) != 2:
    print(f"UNEXPECTED COUNT={len(blocks)}")
    sys.exit(1)

for start, end in sorted(blocks, reverse=True):
    indent = lines[start][:lines[start].find("if")]
    new_block = [
        f"{indent}if not second_workflow_path.exists():\n",
        f"{indent}    raise Exception(f\"The second step workflow file does not exist:{{second_workflow_path}}\")\n",
        f"{indent}with open(second_workflow_path, \"r\", encoding=\"utf-8\") as f:\n",
        f"{indent}    second_workflow_config = json.load(f)\n",
        f"{indent}second_workflow_params = {{\n",
        f"{indent}    \"videoimage\": generated_image_url,\n",
        f"{indent}    \"audio\": audio_path\n",
        f"{indent}}}\n",
        f"{indent}if second_workflow_config.get(\"source\") == \"runninghub\" and \"workflow_id\" in second_workflow_config:\n",
        f"{indent}    workflow_input = second_workflow_config[\"workflow_id\"]\n",
        f"{indent}else:\n",
        f"{indent}    workflow_input = str(second_workflow_config)\n",
        "\n",
        f"{indent}# ===== v2 + 消费级 key 路径（优先） =====\n",
        f"{indent}generated_video_url = None\n",
        f"{indent}if (\n",
        f"{indent}    second_workflow_config.get(\"source\") == \"runninghub\"\n",
        f"{indent}    and \"workflow_id\" in second_workflow_config\n",
        f"{indent}):\n",
        f"{indent}    try:\n",
        f"{indent}        audio_ref = await _rh_v2_upload(audio_path)\n",
        f"{indent}    except Exception as exc:\n",
        f"{indent}        logger.warning(f\"[digital_human] v2 combination upload failed: {{exc}}\")\n",
        f"{indent}        audio_ref = None\n",
        f"{indent}    if audio_ref and generated_image_url:\n",
        f"{indent}        node_info_list = [\n",
        f"{indent}            {{\"nodeId\": \"133\", \"fieldName\": \"image\", \"fieldValue\": generated_image_url}},\n",
        f"{indent}            {{\"nodeId\": \"206\", \"fieldName\": \"audio\", \"fieldValue\": audio_ref}},\n",
        f"{indent}        ]\n",
        f"{indent}        v2_res = await _try_runninghub_v2(\n",
        f"{indent}            workflow_id=workflow_input,\n",
        f"{indent}            node_info_list=node_info_list,\n",
        f"{indent}            expected=\"video\",\n",
        f"{indent}        )\n",
        f"{indent}        if v2_res:\n",
        f"{indent}            generated_video_url = v2_res[\"url\"]\n",
        f"{indent}            logger.info(\n",
        f"{indent}                f\"[digital_human] v2 combination OK: video_url={{generated_video_url}}\"\n",
        f"{indent}            )\n",
        "\n",
        f"{indent}if generated_video_url is None:\n",
        f"{indent}    second_result = await kit.execute(workflow_input, second_workflow_params)\n",
        f"{indent}    if hasattr(second_result, \"videos\") and second_result.videos:\n",
        f"{indent}        generated_video_url = second_result.videos[0]\n",
        f"{indent}    elif hasattr(second_result, \"outputs\") and second_result.outputs:\n",
        f"{indent}        for node_id, node_output in second_result.outputs.items():\n",
        f"{indent}            if isinstance(node_output, dict) and \"videos\" in node_output:\n",
        f"{indent}                videos = node_output[\"videos\"]\n",
        f"{indent}                if videos and len(videos) > 0:\n",
        f"{indent}                    generated_video_url = videos[0]\n",
        f"{indent}                    break\n",
        f"{indent}if not generated_video_url:\n",
        f"{indent}    raise Exception(\"The second step of the workflow did not return a video. Please check the workflow configuration.\")\n"
    ]
    lines[start:end+1] = new_block

with open(path, \"w\", encoding=\"utf-8\") as f:
    f.writelines(lines)
print(\"OK replaced 2\")

