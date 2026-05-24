import json
import os

queue_path = r"f:\codex project\小红书\data\publish_queue.json"
if os.path.exists(queue_path):
    with open(queue_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except Exception:
            data = {}
            
    if isinstance(data, dict):
        jobs = data.get("jobs", {})
        cleaned_jobs = {}
        removed_count = 0
        for jid, job in jobs.items():
            task_id = job.get("task_id", "")
            if task_id in ("e2e_graft_test", "test_graft_task") or "test" in task_id:
                print(f"Removing test job {jid} with status {job.get('status')}")
                removed_count += 1
            else:
                cleaned_jobs[jid] = job
        data["jobs"] = cleaned_jobs
        
        with open(queue_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"Cleaned up {removed_count} test jobs from publish_queue.json")
else:
    print("publish_queue.json does not exist")
