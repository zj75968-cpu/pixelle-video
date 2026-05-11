"""一次性脚本：把双重编码 + 'Result:' 前缀的 registry JSON 修正回普通 JSON 数组。"""
import json
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "pixelle_video" / "services" / "runninghub_lowprice_registry.json"
txt = p.read_text(encoding="utf-8")
print("first 40:", repr(txt[:40]))

# 找到第一个双引号（"Result: " 前缀之后的真正 JSON 字符串开始）
idx = txt.find('"')
if idx < 0:
    raise SystemExit("no quote found")

body = txt[idx:].rstrip()
# 第一层 loads -> 得到内部的真正 JSON 字符串；第二层 loads -> 得到 Python 列表
inner = json.loads(body)
if isinstance(inner, str):
    data = json.loads(inner)
else:
    data = inner

print("decoded len:", len(data))
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("rewrote bytes:", p.stat().st_size)
