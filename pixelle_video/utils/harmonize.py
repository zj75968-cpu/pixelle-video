# Copyright (C) 2025 AIDC-AI
# Licensed under the Apache License, Version 2.0
"""
小红书引流文案谐音化工具

把常见敏感词（加群/微信/V信/扣扣/进群 等）替换为谐音字 + 表情，规避平台风控。
区别于 utils/banned_keywords.py（那个是删除/打码），这里是「重写为谐音」。

使用：
    from pixelle_video.utils.harmonize import harmonize_text, harmonize_hashtags
    title = harmonize_text(title)
    body  = harmonize_text(body)
    tags  = harmonize_hashtags(tags)
"""
from __future__ import annotations

import random
import re
from typing import Iterable, List


# ── 常用敏感词 → 候选谐音/表情（每个 key 随机挑一个候选）─────────────────
# 候选越多，多篇之间差异越大，越不容易被风控聚类
_HARMONIZE_MAP: dict[str, list[str]] = {
    # 加群类
    "加群":    ["+羊", "嘉羊", "扣1进羊", "嘉裙", "加🐏", "+群"],
    "进群":    ["进羊", "近羊", "→羊圈", "进🐏圈", "钻羊"],
    "建群":    ["建羊", "搭羊圈", "拉羊圈"],
    "群聊":    ["羊聊", "🐏聊", "圈聊"],
    "拉你进群": ["拉你进🐏圈", "拉你近羊", "拉你嘉羊"],
    "群":     ["羊", "🐏", "圈圈", "Q"],

    # 联系方式
    "微信":    ["薇❤", "Vx", "V➕", "威❤", "weichat", "v芯"],
    "v信":    ["薇❤", "Vx", "v➕"],
    "VX":     ["Vx", "v➕", "薇❤", "v芯"],
    "vx":     ["薇❤", "v➕", "Vx"],
    "wechat": ["WeC", "Wec", "w-chat"],
    "WeChat": ["WeC", "Wec"],

    "QQ":     ["扣扣", "Q❤", "qq✨", "扣Q"],
    "qq":     ["扣扣", "q❤", "扣q"],
    "扣扣":    ["Q❤", "扣Q", "qq✨"],

    "手机号":   ["📱号", "电话号", "号码"],
    "电话":    ["📱", "电话☎️", "tel"],

    # 引流动作
    "联系我":   ["私我", "🐎我", "扣我", "踢我一脚", "戳我"],
    "联系":    ["私聊", "私🐎", "扣"],
    "私聊":    ["私🐎", "扣我", "踢一脚"],
    "私信":    ["私🐎", "私❤", "私❤️"],
    "DM":     ["dm", "私❤"],
    "dm":     ["私❤", "dm我"],
    "评论扣":   ["评论扣", "扣个", "评论区扣"],
    "评论区":   ["评论区🍃", "💬区", "评❤区"],
    "扣1":    ["扣1️⃣", "扣🈚️1", "扣个1"],
    "回复1":   ["回1️⃣", "回个1"],
    "踢一脚":   ["踢🦶", "踢我一脚"],
    "戳我":    ["戳我✋", "戳一下"],

    # 其它常见违禁/限流词
    "免费":    ["米费", "0元", "白嫖", "0💰"],
    "免费送":   ["白嫖送", "0元送", "送💝"],
    "白嫖":    ["白piao", "白🐎"],
    "添加":    ["d加", "+", "嘉"],
    "兼职":    ["jz", "𝓳𝓩", "兼❤"],
    "副业":    ["fu业", "副❤业", "兼搞"],
    "赚钱":    ["💰💰", "𝓏赚", "搞💴"],
    "代理":    ["dl", "𝓭𝓵", "代❤"],
    "推广":    ["tg", "扣tui"],
    "佣金":    ["yj", "yo金"],

    # 客资引流
    "扫码":    ["sm", "扫🐎", "扫"],
    "二维码":   ["2🐎码", "2维🐎", "扫🐎"],
    "公众号":   ["公🐤号", "公❤号"],
    "小红书":   ["小🍠", "小红🐤", "🍠"],
    "抖音":    ["dy", "🎵", "d音"],
    "快手":    ["ks", "k手"],
    "B站":    ["b站", "biil", "哔站"],
    "淘宝":    ["tb", "🍑宝", "T宝"],
    "拼多多":   ["pdd", "𝓹𝓭𝓭"],

    # 资料/福利
    "资料":    ["zl", "👜料", "z liao"],
    "干货":    ["g货", "干🐮货"],
    "教程":    ["jc", "教❤程", "学❤"],
    "学习":    ["xx", "学❤", "学🥰"],
    "福利":    ["fl", "福❤", "🎁"],
    "限时":    ["xs", "限⏰", "今日限定"],
    "限免":    ["xm", "限❤免"],
    "领取":    ["l取", "🉑领", "领❤"],
}

# 大小写不敏感的键，先按字符长度倒序，保证"加群"先于"群"被替换
_SORTED_KEYS = sorted(_HARMONIZE_MAP.keys(), key=lambda k: -len(k))


def _pick(word: str, seed: int | None) -> str:
    """从候选里挑一个；提供 seed 时确定性挑选，便于"两篇不同"。"""
    pool = _HARMONIZE_MAP.get(word) or _HARMONIZE_MAP.get(word.lower()) or [word]
    if seed is None:
        return random.choice(pool)
    rng = random.Random(seed ^ (hash(word) & 0xFFFFFFFF))
    return rng.choice(pool)


def harmonize_text(text: str, *, seed: int | None = None) -> str:
    """把文本里的敏感词替换为谐音/表情。

    seed: 同一个 seed 替换结果一致；不同 seed 让两篇引流帖出现差异表达。
    """
    if not text:
        return text or ""
    out = text
    for key in _SORTED_KEYS:
        if not key:
            continue
        # 大小写不敏感
        pattern = re.compile(re.escape(key), re.IGNORECASE)
        out = pattern.sub(lambda _m, k=key: _pick(k, seed), out)
    return out


def harmonize_hashtags(tags: Iterable[str] | None, *, seed: int | None = None) -> List[str]:
    """对每个 hashtag 单独谐音化；空标签丢弃。"""
    if not tags:
        return []
    return [harmonize_text(t, seed=seed).strip() for t in tags if t and t.strip()]


def harmonize_pair(text: str) -> tuple[str, str]:
    """生成 A/B 两个差异化谐音版本，用于双发引流帖。"""
    return harmonize_text(text, seed=11), harmonize_text(text, seed=37)


def list_rules() -> dict[str, list[str]]:
    """返回当前内置规则表（UI 调试用）。"""
    return dict(_HARMONIZE_MAP)
