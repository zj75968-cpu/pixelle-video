"""Result files component"""
import streamlit as st
from typing import List, Dict, Any


def render_result_files(files: List[Dict[str, Any]]):
    """
    Render result files component.

    Args:
        files: List of TaskFileResponse dicts
    """
    if not files:
        st.info("No result files available")
        return

    st.markdown("### 📁 Result Files")

    for file in files:
        path = file["path"]
        url = file["url"]
        size = file.get("size", 0)
        mime_type = file.get("mime_type", "application/octet-stream")

        # File info
        size_str = format_file_size(size)
        st.markdown(f"**{path}** ({size_str})")

        # Render based on MIME type
        if mime_type.startswith("video/"):
            st.video(url)
        elif mime_type.startswith("image/"):
            st.image(url, use_column_width=True)
        elif mime_type.startswith("audio/"):
            st.audio(url)
        else:
            st.info(f"File type: {mime_type}")

        # Download link
        st.markdown(f"[⬇️ Download]({url})")
        st.divider()


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.

    Args:
        size_bytes: File size in bytes

    Returns:
        Formatted size string (e.g., "1.50 MB")
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"
