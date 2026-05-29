# -*- coding: utf-8 -*-
import xml.etree.ElementTree as ET
import re
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent

def main():
    path = _project_root / "runtime" / "xhs_album.xml"
    if not path.exists():
        print("File not found")
        return
        
    tree = ET.parse(str(path))
    root = tree.getroot()
    
    count = 0
    for elem in root.iter():
        attrib = elem.attrib
        cls = attrib.get("class", "")
        bounds = attrib.get("bounds", "")
        res_id = attrib.get("resource-id", "")
        desc = attrib.get("content-desc", "")
        text = attrib.get("text", "")
        
        if "ImageView" in cls or "View" in cls:
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if m:
                x1, y1, x2, y2 = map(int, m.groups())
                w = x2 - x1
                h = y2 - y1
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                if 300 < cy < 1800:
                    count += 1
                    print(f"Index {count}: class={cls}, id='{res_id}', desc='{desc}', bounds={bounds}, size={w}x{h} -> Center: X={round(cx/1080,3)}, Y={round(cy/2400,3)}")
                    if count >= 30:
                        break

if __name__ == "__main__":
    main()
