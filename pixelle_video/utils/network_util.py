import socket
import httpx
from loguru import logger

def get_local_physical_ip() -> str:
    """
    获取本机的真实物理网卡 IP，排除 127.0.0.1 和 Clash 虚拟网卡的 198.18.x.x 网段。
    支持从配置读取 local_bind_ip，并提供高鲁棒性的自动选取逻辑（优先排除 VMware 虚拟网卡）。
    """
    # 优先读取配置文件中的 explicit 物理 IP 绑定
    try:
        from pixelle_video.config import config_manager
        dist_cfg = getattr(config_manager.config, "distribution", None)
        configured_ip = (getattr(dist_cfg, "local_bind_ip", "") or "").strip()
        if configured_ip:
            logger.debug(f"[network_util] Using configured local_bind_ip: {configured_ip}")
            return configured_ip
    except Exception as e:
        logger.debug(f"[network_util] Failed to load local_bind_ip from config: {e}")

    try:
        hostname = socket.gethostname()
        ips = socket.gethostbyname_ex(hostname)[2]
        
        preferred_ips = []
        fallback_ips = []
        
        for ip in ips:
            # 排除 127.x.x.x 和 Clash 虚拟网卡 (198.18.x.x)
            if ip.startswith("127.") or ip.startswith("198.18."):
                continue
            
            parts = ip.split(".")
            if len(parts) == 4:
                third_byte = parts[2]
                # 典型的常见家用物理网段 (小米 31, 华硕 50, 常见的 0, 1, 2, 3, 10, 123)
                if parts[0] == "192" and parts[1] == "168" and third_byte in ["0", "1", "2", "3", "31", "50", "10", "123", "8"]:
                    # 真实网卡结尾极少是 .1 (通常是网关或者是宿主机给虚拟机的虚拟网口，如 192.168.77.1)
                    if not ip.endswith(".1"):
                        preferred_ips.append(ip)
                    else:
                        fallback_ips.append(ip)
                elif parts[0] == "10":
                    if not ip.endswith(".1"):
                        preferred_ips.append(ip)
                    else:
                        fallback_ips.append(ip)
                else:
                    # 对于其他的 172.x 段或不知名段
                    fallback_ips.append(ip)
                    
        # 1. 优先使用真实家用网段的非 .1 结尾 IP
        if preferred_ips:
            logger.debug(f"[network_util] Found preferred physical IP: {preferred_ips[0]}")
            return preferred_ips[0]
            
        # 2. 如果没有 preferred，对 fallback 按非 .1 优先的原则进行排序选取
        if fallback_ips:
            fallback_ips.sort(key=lambda x: 1 if x.endswith(".1") else 0)
            logger.debug(f"[network_util] Using fallback physical IP: {fallback_ips[0]}")
            return fallback_ips[0]
            
    except Exception as e:
        logger.debug(f"[network_util] Failed to detect physical IP: {e}")

    # 终极退避
    return "192.168.1.2"

def get_cloud_client(timeout: float = 30.0) -> httpx.Client:
    """
    获取一个绑定了本地物理网口 IP 的 httpx 客户端，用以直连云端、绕过 Clash TUN 的 502 阻断。
    """
    ip = get_local_physical_ip()
    logger.debug(f"[network_util] Creating httpx.Client bound to physical IP: {ip}")
    transport = httpx.HTTPTransport(local_address=ip)
    # trust_env=False 防止它去读系统代理环境变量，使直连更可靠
    return httpx.Client(transport=transport, trust_env=False, timeout=timeout)
