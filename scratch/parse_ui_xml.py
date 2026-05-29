# -*- coding: utf-8 -*-
import re
import xml.etree.ElementTree as ET
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent

# 手机屏幕分辨率
SCREEN_WIDTH = 1080
SCREEN_HEIGHT = 2400

def parse_bounds(bounds_str):
    """解析 bounds 字符串 '[x1,y1][x2,y2]' 并返回中心点 (cx, cy)"""
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
    if m:
        x1, y1, x2, y2 = map(int, m.groups())
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        rx = round(cx / SCREEN_WIDTH, 3)
        ry = round(cy / SCREEN_HEIGHT, 3)
        return cx, cy, rx, ry
    return None

def find_nodes(xml_file, filter_fn):
    """根据过滤函数在 XML 中查找所有符合的节点"""
    path = _project_root / "runtime" / xml_file
    if not path.exists():
        print(f"[WARN] 找不到文件: {path}")
        return []
    
    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
        matches = []
        for elem in root.iter():
            attrib = elem.attrib
            if filter_fn(attrib):
                bounds = attrib.get("bounds", "")
                pts = parse_bounds(bounds)
                if pts:
                    matches.append((attrib, pts))
        return matches
    except Exception as e:
        print(f"[ERROR] 解析 {xml_file} 失败: {e}")
        return []

def main():
    print("==================================================")
    print("         XML 界面结构解析中...")
    print("==================================================")
    
    # 1. 浏览器页面解析
    print("\n[1] 浏览器页面提取:")
    # 寻找输入框 (EditText)，或者 id/desc 包含 search/url/address 的节点
    def browser_bar_filter(a):
        text = a.get("text", "").lower()
        cls = a.get("class", "")
        res_id = a.get("resource-id", "").lower()
        desc = a.get("content-desc", "").lower()
        
        # EditText 且在屏幕上方 (Y < 400)
        if "edittext" in cls.lower():
            bounds_str = a.get("bounds", "")
            pts = parse_bounds(bounds_str)
            if pts and pts[1] < 400:
                return True
        if any(k in text or k in res_id or k in desc for k in ["url", "address", "search", "输入"]):
            bounds_str = a.get("bounds", "")
            pts = parse_bounds(bounds_str)
            if pts and pts[1] < 400:
                return True
        return False
        
    bar_matches = find_nodes("browser_page.xml", browser_bar_filter)
    for a, pts in bar_matches[:3]:
        print(f" -> 候选地址栏: text='{a.get('text')}', id='{a.get('resource-id')}', bounds={a.get('bounds')} -> 比例: X={pts[2]}, Y={pts[3]}")

    # 寻找长按弹窗的保存/下载按钮
    def browser_save_filter(a):
        text = a.get("text", "")
        return any(k in text for k in ["保存图片", "下载图片", "保存视频", "下载视频", "保存到相册", "下载到本地", "保存"])
        
    save_matches = find_nodes("browser_page.xml", browser_save_filter)
    for a, pts in save_matches:
        print(f" -> 候选保存按钮: text='{a.get('text')}', id='{a.get('resource-id')}', bounds={a.get('bounds')} -> 比例: X={pts[2]}, Y={pts[3]}")

    # 2. 小红书首页解析
    print("\n[2] 小红书首页提取:")
    # 寻找底部的加号发布按钮
    def xhs_add_filter(a):
        desc = a.get("content-desc", "")
        text = a.get("text", "")
        res_id = a.get("resource-id", "")
        # 小红书发布按钮通常 desc 是 "发布"、"发布笔记" 或 "+"，在屏幕底部
        if any(k in desc or k in text for k in ["发布", "发笔记", "新增", "发布新内容", "+"]):
            bounds_str = a.get("bounds", "")
            pts = parse_bounds(bounds_str)
            if pts and pts[1] > 2000:
                return True
        if "publish" in res_id.lower() or "post" in res_id.lower():
            bounds_str = a.get("bounds", "")
            pts = parse_bounds(bounds_str)
            if pts and pts[1] > 2000:
                return True
        return False
        
    add_matches = find_nodes("xhs_home.xml", xhs_add_filter)
    for a, pts in add_matches:
        print(f" -> 候选发布+按钮: desc='{a.get('content-desc')}', text='{a.get('text')}', id='{a.get('resource-id')}', bounds={a.get('bounds')} -> 比例: X={pts[2]}, Y={pts[3]}")

    # 3. 小红书相册选图页面解析
    print("\n[3] 小红书选图页面提取:")
    # 寻找“下一步”/“确定”按钮
    def xhs_next_filter(a):
        text = a.get("text", "")
        desc = a.get("content-desc", "")
        res_id = a.get("resource-id", "")
        if any(k in text or k in desc for k in ["下一步", "确定", "继续"]):
            return True
        if "next" in res_id.lower() or "confirm" in res_id.lower():
            return True
        return False
        
    next_matches = find_nodes("xhs_album.xml", xhs_next_filter)
    for a, pts in next_matches:
        print(f" -> 候选下一步按钮: text='{a.get('text')}', desc='{a.get('content-desc')}', id='{a.get('resource-id')}', bounds={a.get('bounds')} -> 比例: X={pts[2]}, Y={pts[3]}")
        
    # 寻找“多选”/“选择多个”按钮
    def xhs_multi_filter(a):
        text = a.get("text", "")
        desc = a.get("content-desc", "")
        return any(k in text or k in desc for k in ["多选", "选择多个", "多张", "批量"])
        
    multi_matches = find_nodes("xhs_album.xml", xhs_multi_filter)
    for a, pts in multi_matches:
        print(f" -> 候选多选按钮: text='{a.get('text')}', desc='{a.get('content-desc')}', id='{a.get('resource-id')}', bounds={a.get('bounds')} -> 比例: X={pts[2]}, Y={pts[3]}")

    # 4. 小红书发帖编辑页解析
    print("\n[4] 小红书发帖编辑页提取:")
    # 寻找“发布笔记”/“发布”按钮
    def xhs_publish_filter(a):
        text = a.get("text", "")
        desc = a.get("content-desc", "")
        res_id = a.get("resource-id", "")
        if any(k in text or k in desc for k in ["发布笔记", "发布"]):
            bounds_str = a.get("bounds", "")
            pts = parse_bounds(bounds_str)
            if pts and pts[1] > 1800: # 在下方
                return True
        if "publish" in res_id.lower() or "post" in res_id.lower():
            bounds_str = a.get("bounds", "")
            pts = parse_bounds(bounds_str)
            if pts and pts[1] > 1800:
                return True
        return False
        
    pub_matches = find_nodes("xhs_edit.xml", xhs_publish_filter)
    for a, pts in pub_matches:
        print(f" -> 候选发布笔记按钮: text='{a.get('text')}', desc='{a.get('content-desc')}', id='{a.get('resource-id')}', bounds={a.get('bounds')} -> 比例: X={pts[2]}, Y={pts[3]}")

if __name__ == "__main__":
    main()
