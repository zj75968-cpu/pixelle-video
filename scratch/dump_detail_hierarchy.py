import sys
import os
from pathlib import Path

# Add project root to sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pixelle_video.services.xhs_publisher import XHSPublisher

SERIAL = "10ACBE28M70044L"

def main():
    print("[*] 正在连接设备...")
    publisher = XHSPublisher(serial=SERIAL, job_id="dump_hierarchy")
    d = publisher._get_device()
    
    # 打印当前页面的 XML 层次结构
    xml = d.dump_hierarchy()
    with open("xhs_detail_dump.xml", "w", encoding="utf-8") as f:
        f.write(xml)
    print("[+] 页面 XML 已经成功导出至 xhs_detail_dump.xml")

if __name__ == "__main__":
    main()
