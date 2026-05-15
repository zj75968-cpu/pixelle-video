
# -*- coding: utf-8 -*-
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
    print("UNEXPECTED COUNT=" + str(len(blocks)))
    sys.exit(1)

for start, end in sorted(blocks, reverse=True):
    indent = lines[start][:lines[start].find("if")]
    new_block = [
        indent + "if not second_workflow_path.exists():\n",
        indent + "    raise Exception(f\"The second step workflow file does not exist:{second_workflow_path}\")\n",
        indent + "with open(second_workflow_path, \"r\", encoding=\"utf-8\") as f:\n",
        indent + "    second_workflow_config = json.load(f)\n",
        indent + "second_workflow_params = {\n",
        indent + "    \"videoimage\": generated_image_url,\n",
        indent + "    \"audio\": audio_path\n",
        indent + "}\n",
        indent + "if second_workflow_config.get(\"source\") == \"runninghub\" and \"workflow_id\" in second_workflow_config:\n",
        indent + "    workflow_input = second_workflow_config[\"workflow_id\"]\n",
        indent + "else:\n",
        indent + "    workflow_input = str(second_workflow_config)\n",
        "\n",
        indent + "# ===== v2 + 消费级 key 路径（优先） =====\n",
        indent + "generated_video_url = None\n",
        indent + "if (\n",
        indent + "    second_workflow_config.get(\"source\") == \"runninghub\"\n",
        indent + "    and \"workflow_id\" in second_workflow_config\n",
        indent + "):\n",
        indent + "    try:\n",
        indent + "        audio_ref = await _rh_v2_upload(audio_path)\n",
        indent + "    except Exception as exc:\n",
        indent + "        logger.warning(f\"[digital_human] v2 combination upload failed: {exc}\")\n",
        indent + "        audio_ref = None\n",
        indent + "    if audio_ref and generated_image_url:\n",
        indent + "        node_info_list = [\n",
        indent + "            {\"nodeId\": \"133\", \"fieldName\": \"image\", \"fieldValue\": generated_image_url},\n",
        indent + "            {\"nodeId\": \"206\", \"fieldName\": \"audio\", \"fieldValue\": audio_ref},\n",
        indent + "        ]\n",
        indent + "        v2_res = await _try_runninghub_v2(\n",
        indent + "            workflow_id=workflow_input,\n",
        indent + "            node_info_list=node_info_list,\n",
        indent + "            expected=\"video\",\n",
        indent + "        )\n",
        indent + "        if v2_res:\n",
        indent + "            generated_video_url = v2_res[\"url\"]\n",
        indent + "            logger.info(\n",
        indent + "                f\"[digital_human] v2 combination OK: video_url={generated_video_url}\"\n",
        indent + "            )\n",
        "\n",
        indent + "if generated_video_url is None:\n",
        indent + "    second_result = await kit.execute(workflow_input, second_workflow_params)\n",
        indent + "    if hasattr(second_result, \"videos\") and second_result.videos:\n",
        indent + "        generated_video_url = second_result.videos[0]\n",
        indent + "    elif hasattr(second_result, \"outputs\") and second_result.outputs:\n",
        indent + "        for node_id, node_output in second_result.outputs.items():\n",
        indent + "            if isinstance(node_output, dict) and \"videos\" in node_output:\n",
        indent + "                videos = node_output[\"videos\"]\n",
        indent + "                if videos and len(videos) > 0:\n",
        indent + "                    generated_video_url = videos[0]\n",
        indent + "                    break\n",
        indent + "if not generated_video_url:\n",
        indent + "    raise Exception(\"The second step of the workflow did not return a video. Please check the workflow configuration.\")\n"
    ]
    lines[start:end+1] = new_block

with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)
print("OK replaced 2")

