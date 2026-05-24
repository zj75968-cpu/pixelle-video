import re

xml_path = r"C:\Users\86136\.gemini\antigravity\brain\aac63459-12c5-4682-ba5b-4297f74a0b6b\device_check_publish_hierarchy.xml"
with open(xml_path, 'r', encoding='utf-8') as f:
    content = f.read()

keywords = ["分享至", "微信", "QQ", "嫁接", "刚刚", "首页"]
for kw in keywords:
    matches = [line for line in content.splitlines() if kw in line]
    print(f"Keyword '{kw}': found {len(matches)} matches")
    for m in matches[:5]:
        print(f"  {m.strip()[:120]}")
