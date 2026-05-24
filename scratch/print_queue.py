import json
import os

queue_path = r"f:\codex project\小红书\data\publish_queue.json"
if os.path.exists(queue_path):
    with open(queue_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print("Jobs in queue:")
    jobs = data.get("jobs", {})
    for jid, job in jobs.items():
        print(f"  ID: {jid} | TaskID: {job.get('task_id')} | Status: {job.get('status')} | Title: {job.get('title')}")
else:
    print("publish_queue.json does not exist")
