# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""
🔄 智能搬运（AI 驱动版）

流程：
  1. 输入主题
  2. AI 联网搜索参考素材（图 + 文）
  3. 每张图反推 prompt → AI 重画（避免版权）
  4. AI 重写文案（标题/正文/标签）
  5. 一键加入发布队列
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st
from loguru import logger

from web.state.session import init_session_state
from web.components.header import render_header
from web.utils.async_helpers import run_async

st.set_page_config(
    page_title="智能搬运 - AI 内容工厂",
    page_icon="🔄",
    layout="wide",
)

init_session_state()
render_header()

from pixelle_video.services.smart_scraper import (
    smart_scrape,
    reverse_prompt as svc_reverse_prompt,
    reverse_prompt_structured as svc_reverse_structured,
    regenerate_image as svc_regenerate_image,
    generate_copy as svc_generate_copy,
    get_channel_status,
    run_xhs_login,
)


# ─── 标题 ─────────────────────────────────────────────────────────────────────

st.title("🔄 智能搬运（AI 驱动）")
st.caption(
    "主题驱动：AI 联网找素材 → 反推 prompt → 重画图片 → 重写文案 → 发布。"
    "全程无 cookie、无平台依赖。"
)


# ─── 数据源状态条（Agent-Reach 集成）─────────────────────────────────────────

def _render_channel_status_bar() -> None:
    """显示 deepsearch 三个数据源（xhs / Exa / ddgs）的实时状态，
    未登录时提供「一键跳转登录」与「自动从浏览器提取 Cookie」按钮。"""
    if "ar_status" not in st.session_state or st.session_state.get("_ar_status_dirty"):
        st.session_state["ar_status"] = get_channel_status()
        st.session_state["_ar_status_dirty"] = False
    s = st.session_state["ar_status"]

    cols = st.columns([2, 2, 2, 1])
    # 小红书
    xhs = s["xhs"]
    with cols[0]:
        if xhs["logged_in"]:
            st.success(f"📕 小红书：已登录 {xhs['username'] or ''}".strip())
        elif xhs["installed"]:
            st.warning("📕 小红书：未登录（将自动回退 Bing）")
        else:
            st.error("📕 小红书 CLI 未安装")
    # Exa
    exa = s["exa"]
    with cols[1]:
        if exa.get("configured"):
            st.success("🌐 Exa：摘要增强已启用")
        elif exa["installed"]:
            st.warning("🌐 Exa：未配置 server")
        else:
            st.error("🌐 mcporter 未安装")
    # ddgs
    ddgs = s["ddgs"]
    with cols[2]:
        if ddgs["installed"]:
            st.success("🔍 Bing：兜底搜图已启用")
        else:
            st.error("🔍 ddgs 未安装")
    # 刷新
    with cols[3]:
        if st.button("🔄 刷新", key="ar_refresh", width="stretch"):
            st.session_state["_ar_status_dirty"] = True
            st.rerun()

    # 未登录小红书时展开登录区
    if xhs["installed"] and not xhs["logged_in"]:
        with st.expander("🔐 激活小红书原生数据源（推荐）", expanded=False):
            st.markdown(
                """
                小红书数据源比 Bing 图片搜索更贴近平台审美：拿到的是**真实笔记的封面 + 文案**，
                可直接用于反推 prompt 与改写文案。

                **方式 A：如果您是在本地电脑运行本项目**
                1. 点击下方按钮在新标签页打开 [www.xiaohongshu.com](https://www.xiaohongshu.com) 并扫码登录
                2. 回到这里选择您的浏览器，点击「自动从浏览器提取 Cookie」即可激活
                """
            )
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                st.link_button(
                    "🌐 打开小红书登录",
                    "https://www.xiaohongshu.com",
                    width="stretch",
                )
            with c2:
                source = st.selectbox(
                    "浏览器",
                    ["auto", "chrome", "edge", "firefox"],
                    key="xhs_login_browser",
                    label_visibility="collapsed",
                )
            with c3:
                if st.button("🔑 自动从浏览器提取 Cookie", key="xhs_do_login", width="stretch"):
                    with st.spinner("从浏览器读取 xiaohongshu.com 的 Cookie..."):
                        res = run_xhs_login(source)
                    if res["ok"]:
                        st.success(f"✅ 登录成功：{res.get('username') or '已激活'}")
                        st.session_state["_ar_status_dirty"] = True
                        st.rerun()
                    else:
                        st.error(f"❌ {res['message']}")

            st.markdown("---")
            st.markdown(
                """
                **方式 B：手动输入 Cookie（推荐远程部署/多用户时使用，非常稳定）**
                1. 电脑浏览器打开 [www.xiaohongshu.com](https://www.xiaohongshu.com) 并登录
                2. 按 **F12** (或右键检查) 打开开发者工具，切换到 **Network (网络)** 标签页
                3. 刷新小红书页面，点击任意以 `xiaohongshu.com` 结尾的请求
                4. 在右侧 **Headers (标头) -> Request Headers (请求标头)** 中找到 `cookie:`
                5. 复制 `cookie:` 后面的那一长串文本，粘贴在下方并点击保存
                """
            )
            
            cookie_input = st.text_area(
                "粘贴小红书 Cookie String",
                placeholder="例如: a1=1903e...; web_session=04008...;",
                key="xhs_manual_cookie_input"
            )
            
            if st.button("🔑 保存并激活小红书 Cookie", key="xhs_manual_login", width="stretch"):
                if not cookie_input.strip():
                    st.error("请输入 Cookie 内容")
                else:
                    cookies = {}
                    for item in cookie_input.split(";"):
                        item = item.strip()
                        if "=" in item:
                            k, v = item.split("=", 1)
                            cookies[k.strip()] = v.strip()
                    
                    if "a1" not in cookies:
                        st.error("❌ Cookie 格式不正确或缺少必要参数（如 `a1`），请确保复制了完整的 Request Headers 里的 Cookie 文本。")
                    else:
                        with st.spinner("正在保存并激活 Cookie..."):
                            try:
                                import json
                                username = st.session_state.get("username") or "default"
                                user_home = _project_root / "data" / "users" / username
                                xhs_config_dir = user_home / ".xiaohongshu-cli"
                                xhs_config_dir.mkdir(parents=True, exist_ok=True)
                                
                                cookie_payload = {**cookies, "saved_at": time.time()}
                                (xhs_config_dir / "cookies.json").write_text(
                                    json.dumps(cookie_payload, indent=2), 
                                    encoding="utf-8"
                                )
                                try:
                                    (xhs_config_dir / "cookies.json").chmod(0o600)
                                except Exception:
                                    pass
                                
                                st.session_state["_ar_status_dirty"] = True
                                st.success("✅ Cookie 保存并激活成功！")
                                time.sleep(1.0)
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 激活失败: {e}")

            st.markdown("---")
            st.markdown(
                """
                **方式 C：手机扫码登录（最省心，支持多用户独立登录）**
                无需找 Cookie，直接使用小红书 App 扫描下方二维码即可。
                """
            )
            
            from web.utils.xhs_qr_login import get_or_create_session, get_session, remove_session
            username = st.session_state.get("username") or "default"
            session = get_session(username)
            
            # 按钮：获取/刷新二维码
            if st.button("🖥️ 获取/刷新登录二维码", key="xhs_qr_get_btn", width="stretch"):
                with st.spinner("正在获取小红书二维码..."):
                    session = get_or_create_session(username, _project_root)
                    # 等待最多 10 秒以让二维码加载出来
                    for _ in range(20):
                        if session.status != "initializing":
                            break
                        time.sleep(0.5)
                st.rerun()
            
            if session:
                if session.status == "initializing":
                    st.info("⏳ 正在初始化浏览器并拉取二维码，请稍候...")
                elif session.status == "waiting_scan":
                    if session.qr_code_base64:
                        st.image(session.qr_code_base64, caption="请使用小红书 App 扫码登录", width=240)
                        
                        col_check, col_cancel = st.columns(2)
                        with col_check:
                            if st.button("🔄 检查登录状态", key="xhs_qr_check_btn", type="primary", width="stretch"):
                                if session.status == "logged_in":
                                    try:
                                        import json
                                        user_home = _project_root / "data" / "users" / username
                                        xhs_config_dir = user_home / ".xiaohongshu-cli"
                                        xhs_config_dir.mkdir(parents=True, exist_ok=True)
                                        
                                        cookie_payload = {**session.cookies, "saved_at": time.time()}
                                        (xhs_config_dir / "cookies.json").write_text(
                                            json.dumps(cookie_payload, indent=2), 
                                            encoding="utf-8"
                                        )
                                        try:
                                            (xhs_config_dir / "cookies.json").chmod(0o600)
                                        except Exception:
                                            pass
                                        
                                        remove_session(username)
                                        st.session_state["_ar_status_dirty"] = True
                                        st.success("🎉 扫码登录成功！状态已激活。")
                                        time.sleep(1.0)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"保存凭证失败: {e}")
                                else:
                                    st.info("⏳ 尚未检测到扫码成功，请在手机上确认同意登录后重试。")
                        with col_cancel:
                            if st.button("❌ 取消登录", key="xhs_qr_cancel_btn", width="stretch"):
                                remove_session(username)
                                st.rerun()
                elif session.status == "logged_in":
                    try:
                        import json
                        user_home = _project_root / "data" / "users" / username
                        xhs_config_dir = user_home / ".xiaohongshu-cli"
                        xhs_config_dir.mkdir(parents=True, exist_ok=True)
                        
                        cookie_payload = {**session.cookies, "saved_at": time.time()}
                        (xhs_config_dir / "cookies.json").write_text(
                            json.dumps(cookie_payload, indent=2), 
                            encoding="utf-8"
                        )
                        try:
                            (xhs_config_dir / "cookies.json").chmod(0o600)
                        except Exception:
                            pass
                        
                        remove_session(username)
                        st.session_state["_ar_status_dirty"] = True
                        st.success("🎉 扫码登录成功！状态已激活。")
                        time.sleep(1.0)
                        st.rerun()
                    except Exception as e:
                        st.error(f"保存凭证失败: {e}")
                elif session.status == "expired":
                    st.error("❌ 二维码已过期，请重新点击「🖥️ 获取/刷新登录二维码」生成。")
                    remove_session(username)
                elif session.status == "failed":
                    st.error("❌ 二维码获取失败，请重试或使用方式 B。")
                    remove_session(username)


_render_channel_status_bar()


# ─── 1. 主题输入 ──────────────────────────────────────────────────────────────

st.subheader("① 输入主题")

topic_presets = {
    "梵高星空绘画教程": {
        "theme": "梵高星空绘画教程",
        "type": "水彩 (Watercolor)",
        "level": "初学者 (Beginner)",
        "style": "清新治愈 (Fresh & Healing)",
    },
    "城市夜景速写": {
        "theme": "城市夜景速写",
        "type": "铅笔 (Pencil)",
        "level": "初学者 (Beginner)",
        "style": "极简线稿 (Minimal Line Art)",
    },
    "人物肖像入门": {
        "theme": "人物肖像入门",
        "type": "彩铅 (Colored Pencil)",
        "level": "进阶者 (Intermediate)",
        "style": "柔和写实 (Soft Realism)",
    },
    "国风山水临摹": {
        "theme": "国风山水临摹",
        "type": "国画 (Ink Wash)",
        "level": "初学者 (Beginner)",
        "style": "东方意境 (Oriental Mood)",
    },
    "自定义": {
        "theme": "",
        "type": "水彩 (Watercolor)",
        "level": "初学者 (Beginner)",
        "style": "清新治愈 (Fresh & Healing)",
    },
}

if "ss_topic_template" not in st.session_state:
    st.session_state["ss_topic_template"] = "梵高星空绘画教程"
if "ss_topic" not in st.session_state:
    st.session_state["ss_topic"] = topic_presets[st.session_state["ss_topic_template"]]["theme"]

    st.markdown("**选择爬取主题模板**")
    st.caption("先选模板，再点套用；也可以直接改下方主题输入。")

    topic_rows = st.container(border=True)
    with topic_rows:
        row1 = st.columns([4, 1])
        with row1[0]:
            preset_name = st.selectbox(
                "主题模板",
                list(topic_presets.keys()),
                index=list(topic_presets.keys()).index(st.session_state["ss_topic_template"]),
                key="ss_topic_template",
            )
        with row1[1]:
            if st.button("套用模板", width="stretch", key="ss_apply_template"):
                st.session_state["ss_topic"] = topic_presets[preset_name]["theme"] if preset_name != "自定义" else st.session_state.get("ss_topic", "")
                st.rerun()

        selected_preset = topic_presets[preset_name]
        type_options = ["水彩 (Watercolor)", "铅笔 (Pencil)", "彩铅 (Colored Pencil)", "国画 (Ink Wash)", "油画 (Oil Painting)"]
        level_options = ["初学者 (Beginner)", "进阶者 (Intermediate)", "高阶者 (Advanced)"]
        style_options = ["清新治愈 (Fresh & Healing)", "极简线稿 (Minimal Line Art)", "柔和写实 (Soft Realism)", "东方意境 (Oriental Mood)", "复古油画 (Vintage Oil)"]
        row2 = st.columns([1, 1, 1])
        with row2[0]:
            art_type = st.selectbox(
                "绘画类型",
                type_options,
                index=type_options.index(selected_preset["type"]),
                key="ss_art_type",
            )
        with row2[1]:
            skill_level = st.selectbox(
                "难度级别",
                level_options,
                index=level_options.index(selected_preset["level"]),
                key="ss_skill_level",
            )
        with row2[2]:
            mood_style = st.selectbox(
                "画面风格",
                style_options,
                index=style_options.index(selected_preset["style"]),
                key="ss_mood_style",
            )

col1, col2, col3 = st.columns([3, 1, 1])
with col1:
    topic = st.text_input(
        "你想做什么主题的小红书？",
        placeholder="例如：早C晚A护肤、上海周末徒步、平价好用的口红...",
        key="ss_topic",
    )
with col2:
    n_refs = st.number_input(
        "参考素材数量", min_value=1, max_value=8, value=4, key="ss_n_refs"
    )
with col3:
    n_regen = st.number_input(
        "重画图片数量", min_value=1, max_value=9, value=4, key="ss_n_regen"
    )

col4, col5 = st.columns([1, 3])
with col4:
    img_size = st.selectbox(
        "图片比例",
        ["3x4", "1x1", "9x16", "4x3", "16x9"],
        index=0,
        key="ss_size",
        help="3x4 / 1x1 适合小红书图文",
    )
with col5:
    style_hint = st.text_input(
        "风格提示（可空，留空让 AI 自主决定）",
        placeholder="例如：日系小清新插画 / 极简北欧风摄影 / 国风手绘",
        key="ss_style",
    )

# ── 多平台搜索来源 ────────────────────────────────────────────────────────
_SOURCE_OPTIONS = [
    "小红书", "Twitter/X", "Reddit", "微博", "B站", "Pixiv",
    "Pinterest", "Behance", "ArtStation", "DeviantArt", "站酷",
    "百度贴吧", "知乎", "微信公众号", "花瓣", "B站文章", "通用图片",
]
ss_sources = st.multiselect(
    "🌐 搜索来源（多平台并行抓取；中文平台用中文 query，外文平台用英文 query）",
    options=_SOURCE_OPTIONS,
    default=st.session_state.get("ss_sources_last", ["小红书", "Pinterest", "通用图片"]),
    key="ss_sources",
)
st.session_state["ss_sources_last"] = ss_sources

st.caption(
    f"当前模板组合：{st.session_state.get('ss_topic_template','—')} · "
    f"{st.session_state.get('ss_art_type','—')} · "
    f"{st.session_state.get('ss_skill_level','—')} · "
    f"{st.session_state.get('ss_mood_style','—')}"
)

run_btn = st.button(
    "🚀 一键生成（搜索 → 反推 → 重画 → 写文案）",
    type="primary",
    width="stretch",
    disabled=not topic.strip(),
)


# ─── 执行 ─────────────────────────────────────────────────────────────────────

if run_btn and topic.strip():
    with st.status("🤖 AI 正在工作...", expanded=True) as status:
        st.write(f"📋 主题：**{topic.strip()}**")
        st.write("🔎 第一步：联网搜索参考素材...")

        try:
            result = run_async(
                smart_scrape(
                    topic=topic.strip(),
                    n_refs=int(n_refs),
                    n_regen=int(n_regen),
                    style_hint=style_hint.strip(),
                    size=img_size,
                    sources=st.session_state.get("ss_sources") or ["小红书", "通用图片"],
                )
            )
        except Exception as e:
            logger.exception("smart_scrape 调用失败")
            status.update(label=f"❌ 失败：{e}", state="error", expanded=True)
            st.stop()

        if not result.ok:
            status.update(label=f"❌ {result.error}", state="error", expanded=True)
            st.session_state["ss_result"] = result
            st.stop()

        st.write(f"✅ 拿到 {len(result.references)} 条素材，重画 {len([f for f in result.frames if f.generated_image])} 张图，文案已生成。")
        status.update(label="✅ 全部完成！", state="complete", expanded=False)

    st.session_state["ss_result"] = result
    st.rerun()


# ─── 2. 结果展示 ──────────────────────────────────────────────────────────────

result = st.session_state.get("ss_result")
if not result:
    st.info("💡 输入主题，点击「一键生成」开始。")
    st.stop()

if not result.ok:
    st.error(f"❌ 生成失败：{result.error}")
    if st.button("🔄 清除并重试"):
        st.session_state.pop("ss_result", None)
        st.rerun()
    st.stop()

st.markdown("---")
st.subheader("② AI 重画结果")
st.caption(f"📂 输出目录：`{result.output_dir}`")

# 把每帧的可编辑状态镜像到 session_state（首次进入时初始化）
# 后续单独「重画/重新反推/排除」操作都基于这份 mutable 副本
if "ss_frames_state" not in st.session_state or st.session_state.get("ss_frames_topic") != result.topic:
    st.session_state["ss_frames_state"] = [
        {
            "ref_image": f.ref_image,
            "image_prompt": f.image_prompt,
            "generated_image": f.generated_image,
            "error": f.error,
            "excluded": False,
            "prompt_parts": dict(getattr(f, "prompt_parts", {}) or {}),
        }
        for f in result.frames
    ]
    st.session_state["ss_frames_topic"] = result.topic

frames_state = st.session_state["ss_frames_state"]

# ── 统计行 ────────────────────────────────────────────────────────────────
ok_count = sum(1 for f in frames_state if f["generated_image"] and Path(f["generated_image"]).exists() and not f["excluded"])
err_count = sum(1 for f in frames_state if f["error"] or not f["generated_image"])
excl_count = sum(1 for f in frames_state if f["excluded"])

stat_col1, stat_col2, stat_col3, stat_col4, stat_col5 = st.columns([1, 1, 1, 2, 2])
stat_col1.metric("✅ 可用", ok_count)
stat_col2.metric("⚠️ 失败", err_count)
stat_col3.metric("🗑 已排除", excl_count)
with stat_col4:
    if st.button("🔍 全部重新反推 prompt", width="stretch",
                 help="并发批量反推 prompt（默认 3 并发），用于参考图微调后重新理解"):
        targets = [
            (idx, f["ref_image"]) for idx, f in enumerate(frames_state)
            if not f["excluded"] and f["ref_image"] and Path(f["ref_image"]).exists()
        ]
        if not targets:
            st.warning("没有可反推的参考图")
        else:
            from pixelle_video.services.smart_scraper import batch_reverse_prompt
            with st.spinner(f"并发反推 {len(targets)} 张..."):
                results_rev = run_async(batch_reverse_prompt(
                    [p for _, p in targets],
                    concurrency=3,
                ))
            ok_n = 0
            for (idx, _), r in zip(targets, results_rev):
                if r["prompt"]:
                    frames_state[idx]["image_prompt"] = r["prompt"]
                    if r.get("parts"):
                        frames_state[idx]["prompt_parts"] = r["parts"]
                    ok_n += 1
                else:
                    frames_state[idx]["error"] = r["error"]
            st.toast(f"反推完成：{ok_n}/{len(targets)} 成功",
                     icon="✅" if ok_n == len(targets) else "⚠️")
            st.rerun()
with stat_col5:
    if st.button("♻️ 全部用当前 prompt 重画", width="stretch",
                 help="并发批量重新生成（默认 3 并发），可用于风格微调后整体刷新"):
        # 构建待重画任务（跳过已排除的）
        ts_batch = int(time.time())
        pending = [
            {
                "idx": idx,
                "prompt": f["image_prompt"] or "",
                "save_path": str(Path(result.output_dir) / "generated" / f"img_{idx + 1:02d}_v{ts_batch}.png"),
            }
            for idx, f in enumerate(frames_state)
            if not f["excluded"] and (f["image_prompt"] or "").strip()
        ]
        if not pending:
            st.warning("没有可重画的图（全部被排除或 prompt 为空）")
        else:
            prog = st.progress(0.0, text=f"批量重画 0/{len(pending)}")
            done_holder = {"n": 0}

            def _cb(done, total, idx, ok):
                done_holder["n"] = done
                # 注意：streamlit 不允许在异步线程调 UI，所以这里只更新计数

            from pixelle_video.services.smart_scraper import batch_regenerate
            with st.spinner(f"并发重画 {len(pending)} 张..."):
                results_batch = run_async(batch_regenerate(
                    pending,
                    size=img_size,
                    style_hint=style_hint.strip(),
                    concurrency=3,
                    progress_cb=_cb,
                ))
            # 回写结果
            ok_n = 0
            for r in results_batch:
                f = frames_state[r["idx"]]
                if r["ok"]:
                    f["generated_image"] = r["path"]
                    f["error"] = None
                    ok_n += 1
                else:
                    f["error"] = r["error"]
            prog.progress(1.0, text=f"完成 {ok_n}/{len(pending)} 成功")
            st.toast(f"批量重画完成：{ok_n}/{len(pending)} 成功", icon="✅" if ok_n == len(pending) else "⚠️")
            st.rerun()

# ── 每张图详情卡 ──────────────────────────────────────────────────────────
for idx, f in enumerate(frames_state):
    is_ok = bool(f["generated_image"]) and Path(f["generated_image"]).exists()
    is_excluded = f["excluded"]

    status_emoji = "🗑" if is_excluded else ("✅" if is_ok else "⚠️")
    prompt_preview = (f["image_prompt"] or "").replace("\n", " ")[:60]
    if len(f["image_prompt"] or "") > 60:
        prompt_preview += "..."

    with st.expander(
        f"{status_emoji} 第 {idx + 1} 张 — {prompt_preview or '(无 prompt)'}",
        expanded=False,
    ):
        # side-by-side：原图 ↔ 重画图
        img_col1, img_col2 = st.columns(2)
        with img_col1:
            st.caption("📷 原参考图")
            if Path(f["ref_image"]).exists():
                st.image(f["ref_image"], width="stretch")
            else:
                st.info("参考图已丢失")
        with img_col2:
            st.caption("🎨 AI 重画")
            if is_ok:
                st.image(f["generated_image"], width="stretch")
            else:
                st.warning(f"未生成 / 失败：{f['error'] or '未知'}")

        # 结构化 prompt chips（如果有 parts）
        parts = f.get("prompt_parts") or {}
        if parts and any(parts.values()):
            _CHIP_COLORS = {
                "subject":     ("#fde68a", "#92400e"),  # 主体：黄
                "style":       ("#bfdbfe", "#1e40af"),  # 风格：蓝
                "lighting":    ("#fed7aa", "#9a3412"),  # 光线：橙
                "palette":     ("#fbcfe8", "#9d174d"),  # 色调：粉
                "composition": ("#c7d2fe", "#3730a3"),  # 构图：靛
                "mood":        ("#bbf7d0", "#166534"),  # 氛围：绿
            }
            _LABEL_CN = {
                "subject": "主体", "style": "风格", "lighting": "光线",
                "palette": "色调", "composition": "构图", "mood": "氛围",
            }
            chips_html = ['<div style="display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 8px 0;">']
            for k in ["subject", "style", "lighting", "palette", "composition", "mood"]:
                v = (parts.get(k) or "").strip()
                if not v:
                    continue
                bg, fg = _CHIP_COLORS[k]
                # 转义
                v_safe = v.replace("<", "&lt;").replace(">", "&gt;")
                chips_html.append(
                    f'<span style="background:{bg};color:{fg};padding:3px 10px;'
                    f'border-radius:12px;font-size:12px;line-height:1.5;">'
                    f'<b>{_LABEL_CN[k]}</b>：{v_safe}</span>'
                )
            chips_html.append("</div>")
            st.markdown("".join(chips_html), unsafe_allow_html=True)

            with st.expander("✏️ 按维度精修", expanded=False):
                pcols = st.columns(2)
                edited = {}
                for i_k, k in enumerate(["subject", "style", "lighting", "palette", "composition", "mood"]):
                    with pcols[i_k % 2]:
                        edited[k] = st.text_area(
                            _LABEL_CN[k], value=parts.get(k, ""),
                            height=70, key=f"ss_part_{idx}_{k}",
                        )
                if st.button("🧬 合成并保存到 Prompt", key=f"ss_compose_{idx}",
                             width="stretch"):
                    f["prompt_parts"] = edited
                    composed = ", ".join(
                        edited[k].strip().rstrip(".,;")
                        for k in ["subject", "style", "lighting", "palette", "composition", "mood"]
                        if edited.get(k, "").strip()
                    )
                    f["image_prompt"] = composed
                    st.toast("✅ 已合成 Prompt", icon="🧬")
                    st.rerun()

        # 可编辑 prompt（完整文本）
        new_prompt = st.text_area(
            "Prompt（可手动编辑）",
            value=f["image_prompt"] or "",
            height=110,
            key=f"ss_prompt_edit_{idx}",
        )

        # 操作按钮
        btn1, btn2, btn3, btn4 = st.columns([1, 1, 1, 1])
        with btn1:
            if st.button("🔁 用此 prompt 重画", key=f"ss_regen_{idx}", width="stretch"):
                f["image_prompt"] = new_prompt
                try:
                    gen_path = Path(result.output_dir) / "generated" / f"img_{idx + 1:02d}_v{int(time.time())}.png"
                    f["generated_image"] = run_async(
                        svc_regenerate_image(
                            new_prompt,
                            save_path=str(gen_path),
                            size=img_size,
                            style_hint=style_hint.strip(),
                        )
                    )
                    f["error"] = None
                    st.toast("✅ 重画完成", icon="🎨")
                except Exception as e:
                    f["error"] = str(e)
                    st.toast(f"❌ 重画失败：{e}", icon="⚠️")
                st.rerun()
        with btn2:
            if st.button("🔍 重新反推 prompt", key=f"ss_reverse_{idx}", width="stretch",
                         disabled=not Path(f["ref_image"]).exists()):
                try:
                    new_parts = run_async(svc_reverse_structured(f["ref_image"]))
                    f["image_prompt"] = new_parts.get("full", "") or f["image_prompt"]
                    f["prompt_parts"] = {k: v for k, v in new_parts.items() if k != "full"}
                    st.toast("✅ 已重新反推（结构化）", icon="🔍")
                except Exception as e:
                    st.toast(f"❌ 反推失败：{e}", icon="⚠️")
                st.rerun()
        with btn3:
            label = "↩️ 取消排除" if is_excluded else "🗑 排除发布"
            if st.button(label, key=f"ss_excl_{idx}", width="stretch"):
                f["excluded"] = not is_excluded
                st.rerun()
        with btn4:
            # 同步当前编辑框文本到 state（避免用户改了但没点重画就丢失）
            if new_prompt != f["image_prompt"]:
                f["image_prompt"] = new_prompt

# 把失败项放到末尾再单独提示一下（旧逻辑兼容）
err_frames_inline = [f for f in frames_state if f["error"] and not f["generated_image"]]
if err_frames_inline:
    st.info(f"💡 上方有 {len(err_frames_inline)} 张图未成功生成，可以打开对应详情卡，编辑 prompt 后点「🔁 用此 prompt 重画」重试。")


# ─── 3. 文案编辑 ──────────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("③ AI 生成文案（可编辑）")

cur_title = st.session_state.get("ss_edit_title", result.title)
cur_body = st.session_state.get("ss_edit_body", result.body)
cur_tags = st.session_state.get("ss_edit_tags", " ".join(result.hashtags))

edit_title = st.text_input("标题", value=cur_title, key="ss_title_input")
edit_body = st.text_area("正文", value=cur_body, height=240, key="ss_body_input")
edit_tags = st.text_input(
    "标签（空格分隔，不需要 #）",
    value=cur_tags,
    key="ss_tags_input",
)

regen_col1, regen_col2 = st.columns([1, 1])
with regen_col1:
    if st.button("✍️ 重新生成文案", width="stretch"):
        try:
            copy = run_async(svc_generate_copy(result.topic, result.references))
            st.session_state["ss_edit_title"] = copy["title"]
            st.session_state["ss_edit_body"] = copy["body"]
            st.session_state["ss_edit_tags"] = " ".join(copy["hashtags"])
            st.rerun()
        except Exception as e:
            st.error(f"文案重生成失败：{e}")
with regen_col2:
    if st.button("🧹 清空结果重新开始", width="stretch"):
        for k in [
            "ss_result", "ss_edit_title", "ss_edit_body", "ss_edit_tags",
            "ss_frames_state", "ss_frames_topic",
        ]:
            st.session_state.pop(k, None)
        st.rerun()


# ─── 4. 发布到队列 ────────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("④ 发布到小红书")


@st.cache_resource
def _get_publish_scheduler():
    from pixelle_video.services.publish_scheduler import publish_scheduler
    return publish_scheduler


@st.cache_resource
def _get_device_manager():
    from pixelle_video.services.device_manager import device_manager
    return device_manager


dm = _get_device_manager()
try:
    dm.sync_connected()
except Exception as e:
    logger.warning(f"sync_connected 失败：{e}")

all_devices = dm.get_all()
connected = [d for d in all_devices if getattr(d, "connected", False)]

final_images = [
    f["generated_image"]
    for f in frames_state
    if f["generated_image"]
    and Path(f["generated_image"]).exists()
    and not f["excluded"]
]

if not final_images:
    st.warning("⚠️ 还没有可用的重画图，无法发布。请先重新生成。")
else:
    st.caption(f"将发布 **{len(final_images)}** 张 AI 重画图")

    if not connected:
        st.error("❌ 没有已连接的小红书设备。请到「📱 Publish」或「⚙️ Settings」配置设备。")
    else:
        dev_opts = {
            f"{d.serial} - {getattr(d, 'name', '') or '未命名'}": d.serial
            for d in connected
        }
        sel = st.multiselect(
            "选择发布设备",
            options=list(dev_opts.keys()),
            default=list(dev_opts.keys())[:1],
            key="ss_devices",
        )

        schedule_mode = st.radio(
            "发布时间",
            ["立即发布", "📅 按计划自动安排"],
            horizontal=True,
            key="ss_sched_mode",
        )

        if st.button("📤 加入发布队列", type="primary", width="stretch"):
            if not edit_title.strip():
                st.error("标题不能为空")
            elif not sel:
                st.error("请选择至少一台设备")
            else:
                scheduler = _get_publish_scheduler()
                hashtags = [t.lstrip("#") for t in edit_tags.split() if t.strip()]
                task_id = f"smart_{int(time.time())}"

                created = []
                failed = []
                for label in sel:
                    serial = dev_opts[label]
                    try:
                        if schedule_mode == "📅 按计划自动安排":
                            slot = scheduler.next_available_slot(serial)
                            scheduled_at = slot.isoformat() if slot else None
                        else:
                            scheduled_at = None

                        job = scheduler.add_job(
                            serial=serial,
                            task_id=task_id,
                            title=edit_title.strip(),
                            body=edit_body.strip(),
                            hashtags=hashtags,
                            images=final_images,
                            scheduled_at=scheduled_at,
                            kind="image_text",
                            post_type="content",
                        )
                        created.append(job.job_id)
                    except Exception as e:
                        failed.append(f"{serial}: {e}")

                if created:
                    st.success(
                        f"✅ 已创建 {len(created)} 个发布任务。\n"
                        f"前往「📱 Publish」页面查看队列状态。"
                    )
                if failed:
                    st.error("部分失败：" + " | ".join(failed))


# ─── 5. 参考素材（可折叠） ────────────────────────────────────────────────────

with st.expander("📚 查看 AI 搜到的原始参考素材（仅供对比）", expanded=False):
    for i, ref in enumerate(result.references):
        st.markdown(f"**【参考 {i + 1}】{ref.title}**")
        if ref.source_url:
            st.markdown(f"🔗 [{ref.source_url}]({ref.source_url})")
        st.text(ref.text[:300])
        if ref.local_images:
            cols = st.columns(min(len(ref.local_images), 4))
            for c, img in zip(cols, ref.local_images):
                if Path(img).exists():
                    with c:
                        st.image(img, width="stretch")
        st.markdown("---")
