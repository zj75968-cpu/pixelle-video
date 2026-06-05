"""Task status component"""
import streamlit as st
from datetime import datetime
from typing import Dict, Any, Optional


def render_task_status(task: Dict[str, Any], show_cancel: bool = True) -> Optional[str]:
    """
    Render task status component.

    Args:
        task: TaskResponse dict
        show_cancel: Show cancel button for running tasks

    Returns:
        Action string if user clicked cancel, None otherwise
    """
    status = task["status"]
    task_id = task["task_id"]

    # Status badge
    status_colors = {
        "PENDING": "🟡",
        "RUNNING": "🔵",
        "COMPLETED": "🟢",
        "FAILED": "🔴",
        "CANCELLED": "⚫"
    }

    col1, col2, col3 = st.columns([2, 6, 2])

    with col1:
        st.markdown(f"### {status_colors.get(status, '⚪')} {status}")

    with col2:
        # Progress bar for running tasks
        if status == "RUNNING" and task.get("progress"):
            progress = task["progress"]
            percentage = progress.get("percentage", 0)
            message = progress.get("message", "Processing...")
            st.progress(percentage / 100.0)
            st.caption(f"{percentage:.1f}% - {message}")
        elif status == "FAILED" and task.get("error"):
            st.error(f"Error: {task['error']}")
        elif status == "COMPLETED":
            st.success("Task completed successfully")
        else:
            st.info("Task is pending...")

    with col3:
        # Elapsed time
        created_at = datetime.fromisoformat(task["created_at"].replace("Z", "+00:00"))
        updated_at = datetime.fromisoformat(task["updated_at"].replace("Z", "+00:00"))
        elapsed = (updated_at - created_at).total_seconds()
        st.caption(f"⏱️ {elapsed:.1f}s")

        # Cancel button
        if show_cancel and status == "RUNNING":
            if st.button("Cancel", key=f"cancel_{task_id}"):
                return "cancel"

    return None
