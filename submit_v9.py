import urllib.request, json, time

body = json.dumps({
    "serial": "KLXDU20611012075",
    "task_id": "20260504_150647_4b6f",
    "title": "V4-smoke-v9",
    "body": "V4 ADB唤醒屏幕修复",
    "hashtags": [],
    "images": ["output/20260504_150647_4b6f/images/1.png", "output/20260504_150647_4b6f/images/2.png"]
}).encode()

req = urllib.request.Request(
    "http://localhost:8000/api/publish/jobs",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST"
)
with urllib.request.urlopen(req) as r:
    result = json.loads(r.read())
    job_id = result["created"][0]["job_id"]
    print(f"Job ID: {job_id}")

# Wait and poll
for i in range(24):
    time.sleep(10)
    req2 = urllib.request.Request(f"http://localhost:8000/api/publish/jobs/{job_id}")
    with urllib.request.urlopen(req2) as r2:
        status = json.loads(r2.read())
        print(f"[{i*10}s] status={status['status']} error={status.get('error')}")
        if status["status"] in ("completed", "failed"):
            break
