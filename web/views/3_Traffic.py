# Copyright (C) 2025 AIDC-AI
# Licensed under the Apache License, Version 2.0
"""
🔥 引流帖 —— 一键排期多轮自动发布 + 自动删除 + 谐音规避

工作流：
1. 输入：主题 / CTA / 轮数 / 间隔 / 设备 / 图片（上传或路径）
2. 点击「🔮 AI 生成 2 篇预览」→ 调用 LLM 产出两篇不同人设的文案（已谐音化）
3. 编辑/确认 → 点击「🚀 一键排期 N 轮」→ 把所有 job 投进 publish_scheduler 队列
4. 队列里 traffic 类型 job 会在到点后自动发，发完 25min 后自动删
5. 活动列表 → 可一键「⏹ 停止」剩余未发的轮次
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from pixelle_video.services.drainage_loop import (
    campaign_progress,
    generate_drainage_pair,
    list_campaigns,
    schedule_campaign,
    stop_campaign,
)

st.set_page_config(page_title="🔥 引流帖", page_icon="🔥", layout="wide")
st.title("🔥 引流帖 —— 多轮循环发 + 25min 自动删")

st.caption(
    "⚠️ 每轮 2 篇 traffic 帖；每篇发出后按 delete_minutes 自动删除，"
    "轮与轮间隔 = delete_minutes + random(gap_min, gap_max)。"
    "不想再发了点「手动停止循环」只会取消未发 job，已发的让 TTL 自动删。"
)


# ── 设备 ──────────────────────────────────────────────────────────────────
def _get_dm():
    from pixelle_video.services.device_manager import device_manager
    return device_manager


dm = _get_dm()
devices = [d for d in dm.get_all() if d.connected]


# ── 表单：活动参数 + 图片 ─────────────────────────────────────────────────
with st.expander("🎯 新建引流活动", expanded=True):
    col_a, col_b, col_c = st.columns([2, 1, 1])
    with col_a:
        topic = st.text_input(
            "主题 / 赛道",
            value=st.session_state.get("dr_topic", ""),
            placeholder="例：考研英语单词、宝妈副业、健身减脂…",
            key="dr_topic",
        )
        cta = st.text_input(
            "CTA 引流话术（会自动谐音化）",
            value=st.session_state.get("dr_cta", "评论扣 1 进群一起学"),
            help="LLM 会基于这个 CTA 自然写进文末，并谐音化避免敏感词。",
            key="dr_cta",
        )
    with col_b:
        st.markdown("**🔄 循环模式**")
        st.caption("一直发，直到点「⏹ 手动停止循环」。后台一次性预排 100 轮 ≈ 50h。")
        rounds = 100  # 固定大上限，相当于「持续循环」；停止靠用户点按钮
        delete_minutes = st.number_input(
            "每篇存活分钟数（TTL 自动删）",
            min_value=5, max_value=120, value=25, step=1, key="dr_del",
            help="每篇 traffic 帖发出后，过这么多分钟被后台 TTL watcher 自动删。同时作为轮间间隔基准。",
        )
    with col_c:
        gap_min = st.number_input("轮间最小间隔(分)", min_value=1, max_value=60, value=5, step=1, key="dr_gmin")
        gap_max = st.number_input("轮间最大间隔(分)", min_value=1, max_value=120, value=10, step=1, key="dr_gmax")

    # ── 设备 ──
    if not devices:
        st.warning("没有已连接的设备。请到 📱 Publish / 设备管理 连接手机后再来。")
        selected_serials = []
    else:
        device_options = {f"{d.name or d.serial} ({d.serial})": d.serial for d in devices}
        labels = st.multiselect(
            "目标设备（每台都会按这套计划发）",
            options=list(device_options.keys()),
            default=list(device_options.keys())[:1],
            key="dr_devices",
        )
        selected_serials = [device_options[l] for l in labels]

    # ── 图片池 ──
    st.markdown("**🖼️ 图片池**（每篇随机抽 N 张，可上传或粘贴绝对路径）")
    up_files = st.file_uploader(
        "上传图片（多选）",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="dr_uploads",
    )
    paths_raw = st.text_area(
        "或粘贴图片绝对路径（一行一张）",
        height=80,
        key="dr_paths",
        placeholder=r"D:\photos\a.jpg",
    )
    images_per_post = st.number_input(
        "每篇随机抽几张图", min_value=1, max_value=9, value=1, step=1, key="dr_imgs_per"
    )

    # ── AI 预览 ──
    if "dr_pair" not in st.session_state:
        st.session_state["dr_pair"] = []

    col_gen, _ = st.columns([1, 5])
    with col_gen:
        if st.button("🔮 AI 生成 2 篇预览", type="secondary", width="stretch"):
            if not topic.strip():
                st.error("请先填主题")
            else:
                with st.spinner("LLM 生成中…"):
                    try:
                        pair = asyncio.run(
                            generate_drainage_pair(topic.strip(), cta.strip(), seed=int(time.time()))
                        )
                        st.session_state["dr_pair"] = pair
                        st.success(f"✅ 已生成 {len(pair)} 篇，可在下方编辑后排期。")
                    except Exception as e:
                        st.error(f"生成失败：{e}")

    pair = st.session_state.get("dr_pair") or []
    if pair:
        st.markdown("---")
        edited_pair = []
        cols = st.columns(2)
        for i, post in enumerate(pair):
            with cols[i]:
                st.markdown(f"**📝 第 {i+1} 篇 · 人设：{post.get('persona','—')}**")
                
                # 如果有 AI 自动生成的萌系海报，直接展示
                img_path = post.get("image_path")
                if img_path and Path(img_path).exists():
                    st.image(img_path, caption=f"🎨 AI 自动生成海报 {i+1}", use_container_width=True)
                
                t = st.text_input("标题", value=post["title"], key=f"dr_t_{i}")
                b = st.text_area("正文", value=post["body"], height=240, key=f"dr_b_{i}")
                tags_str = st.text_input(
                    "Hashtags（逗号分隔）",
                    value=", ".join(post.get("hashtags") or []),
                    key=f"dr_h_{i}",
                )
                tags = [s.strip().lstrip("#") for s in tags_str.split(",") if s.strip()]
                edited_pair.append({
                    "title": t.strip(),
                    "body": b.strip(),
                    "hashtags": tags,
                    "image_path": img_path,
                })

        st.markdown("---")
        if st.button(
            f"🚀 启动循环发布（预排 {rounds} 轮 × 2 篇 × {max(1,len(selected_serials))} 台）",
            type="primary",
            width="stretch",
        ):
            # 图片池组装
            img_paths: list[str] = []
            if up_files:
                save_dir = Path("output") / "drainage_uploads" / datetime.now().strftime("%Y%m%d_%H%M%S")
                save_dir.mkdir(parents=True, exist_ok=True)
                for f in up_files:
                    p = save_dir / f.name
                    p.write_bytes(f.getbuffer())
                    img_paths.append(str(p.resolve()))
            for line in (paths_raw or "").splitlines():
                line = line.strip().strip('"')
                if line and Path(line).exists():
                    img_paths.append(line)

            errors = []
            if not selected_serials:
                errors.append("未选设备")
            
            # 如果图片池为空，但有自动生成的 AI 海报，这是完全允许的！
            has_ai_posters = all(post.get("image_path") and Path(post["image_path"]).exists() for post in edited_pair)
            if not img_paths and not has_ai_posters:
                errors.append("图片池为空（请先生成 AI 文案/海报或手动上传图片）")
                
            if not edited_pair or len(edited_pair) != 2:
                errors.append("需要先生成 2 篇文案")
            if errors:
                st.error("无法排期：" + "；".join(errors))
            else:
                # 若图片池为空，我们在排期前，自动以用户修改后的最新标题重新渲染海报，保证文字100%同步！
                if not img_paths:
                    with st.spinner("正在根据最新标题同步渲染海报..."):
                        for idx, post in enumerate(edited_pair):
                            old_poster = pair[idx].get("image_path")
                            if post["title"]:
                                try:
                                    from pixelle_video.services.poster_generator import generate_drainage_poster
                                    if old_poster:
                                        generate_drainage_poster(post["title"], old_poster)
                                        post["image_path"] = old_poster
                                    else:
                                        p_dir = Path("output") / "drainage_posters"
                                        p_dir.mkdir(parents=True, exist_ok=True)
                                        import uuid
                                        new_p = p_dir / f"poster_{uuid.uuid4().hex[:12]}.png"
                                        generate_drainage_poster(post["title"], str(new_p.resolve()))
                                        post["image_path"] = str(new_p.resolve())
                                except Exception as exc:
                                    st.warning(f"重新同步海报 {idx+1} 失败: {exc}")
                                    if old_poster:
                                        post["image_path"] = old_poster

                try:
                    campaign = schedule_campaign(
                        serials=selected_serials,
                        image_pool=img_paths,
                        posts=edited_pair,
                        rounds=int(rounds),
                        delete_minutes=int(delete_minutes),
                        gap_min=int(gap_min),
                        gap_max=int(max(gap_max, gap_min)),
                        topic=topic.strip(),
                        cta=cta.strip(),
                        images_per_post=int(images_per_post),
                    )
                    st.success(
                        f"✅ 活动 `{campaign.campaign_id}` 已排期，共 "
                        f"{len(campaign.job_ids)} 个 job。"
                    )
                    st.session_state["dr_pair"] = []
                except Exception as e:
                    st.error(f"排期失败：{e}")


# ── 活动列表 ──────────────────────────────────────────────────────────────
st.markdown("---")
header_col, refresh_col, interval_col = st.columns([4, 1, 1])
header_col.subheader("📋 我的引流活动")
auto_refresh = refresh_col.toggle(
    "🔄 自动刷新",
    value=st.session_state.get("dr_auto_refresh", True),
    key="dr_auto_refresh",
)
refresh_interval = interval_col.number_input(
    "间隔(秒)",
    min_value=3,
    max_value=120,
    value=st.session_state.get("dr_refresh_interval", 10),
    step=1,
    key="dr_refresh_interval",
    label_visibility="collapsed",
)


def _fmt_countdown(sec: int | None) -> str:
    if sec is None:
        return "—"
    if sec <= 0:
        return "🚀 即将发布…"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"⏳ {h}h{m:02d}m{s:02d}s"
    return f"⏳ {m:02d}:{s:02d}"


campaigns = list_campaigns()
if not campaigns:
    st.info("还没有引流活动。配置好之后点上面的「🚀 一键排期」。")
else:
    for c in campaigns:
        prog = campaign_progress(c)
        total = prog["total"] or 1
        done = prog["done"]
        pending = prog["pending"]
        failed = prog["failed"]
        next_eta = prog["next_eta_seconds"]

        with st.container(border=True):
            top_cols = st.columns([3, 2, 2, 2, 2])
            top_cols[0].markdown(
                f"**`{c.campaign_id}`** · `{c.status}`\n\n"
                f"主题：{c.topic or '—'}\n\n"
                f"CTA：{c.cta or '—'}"
            )
            top_cols[1].markdown(
                f"📅 创建：`{c.created_at[:19]}`\n\n"
                f"⚙️ {c.rounds} 轮 × 2 篇 × {len(c.serials)} 台\n\n"
                f"🗑️ 存活 {c.delete_minutes} 分钟（TTL 自动删）"
            )
            top_cols[2].metric("已发", done)
            top_cols[3].metric("待发", pending)
            top_cols[4].metric("失败/取消", failed)

            progress_value = min(1.0, max(0.0, (done + failed) / total))
            label = (
                f"进度 {done + failed}/{total}"
                f" · 距下一篇 {_fmt_countdown(next_eta)}"
                + (
                    f" · 下次：`{prog['next_at'].strftime('%H:%M:%S')}`"
                    if prog["next_at"]
                    else ""
                )
            )
            st.progress(progress_value, text=label)

            stop_disabled = c.status == "stopped" or pending == 0
            btn_cols = st.columns([2, 1, 4])
            if btn_cols[0].button(
                "⏹ 手动停止循环（只取消未发）",
                key=f"stop_{c.campaign_id}",
                disabled=stop_disabled,
                width="stretch",
                help="已发的会由 TTL watcher 按 delete_minutes 自动删除，不需人工干预。",
            ):
                r = stop_campaign(c.campaign_id, delete_published=False)
                st.success(
                    f"✅ 已取消 {r['cancelled']} 个未发 job。已发笔记将由 TTL 自动删。"
                )
                st.rerun()


# ── 自动刷新（用 components.html 注入 setTimeout） ─────────────────────────
if auto_refresh and campaigns and any(
    campaign_progress(c)["pending"] > 0 for c in campaigns
):
    import streamlit.components.v1 as components
    components.html(
        f"""
        <script>
          setTimeout(function() {{
            window.parent.location.reload();
          }}, {int(refresh_interval) * 1000});
        </script>
        """,
        height=0,
    )
