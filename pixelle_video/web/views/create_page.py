"""Create page - Task submission and monitoring"""
import streamlit as st
import time
from pixelle_video.web.api.client import APIClient
from pixelle_video.web.api.tasks import TaskAPI
from pixelle_video.web.components.task_status import render_task_status
from pixelle_video.web.components.result_files import render_result_files
from pixelle_video.web.state.session import (
    init_task_state,
    add_active_task,
    remove_active_task,
    add_to_task_history,
    get_active_tasks
)


def render():
    """Render the Create page"""
    # Initialize
    st.set_page_config(page_title="Create Task", page_icon="🎬")
    init_task_state()

    # API client
    api_client = APIClient(base_url="http://localhost:8000")
    task_api = TaskAPI(api_client)

    st.title("🎬 Create Video Task")

    # Task submission form
    with st.form("task_form"):
        st.subheader("Task Parameters")

        # Example form fields
        task_type = st.selectbox("Task Type", ["VIDEO_GENERATION", "IMAGE_GENERATION"])
        prompt = st.text_area("Prompt", placeholder="Enter your prompt here...")

        submitted = st.form_submit_button("Submit Task")

        if submitted:
            if not prompt:
                st.error("Please enter a prompt")
            else:
                try:
                    # Submit task via API
                    response = api_client.post("/api/tasks", json={
                        "task_type": task_type,
                        "prompt": prompt
                    })
                    task_id = response["task_id"]
                    add_active_task(task_id)
                    st.success(f"Task submitted: {task_id}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to submit task: {e}")

    # Active tasks section
    active_tasks = get_active_tasks()
    if active_tasks:
        st.divider()
        st.subheader("Active Tasks")

        for task_id in active_tasks:
            try:
                task = task_api.get_task_status(task_id)
                if not task:
                    remove_active_task(task_id)
                    continue

                # Render task status
                action = render_task_status(task, show_cancel=True)

                # Handle cancel action
                if action == "cancel":
                    if task_api.cancel_task(task_id):
                        st.success(f"Task {task_id} cancelled")
                        remove_active_task(task_id)
                        st.rerun()

                # Handle completed tasks
                if task["status"] in ["COMPLETED", "FAILED", "CANCELLED"]:
                    remove_active_task(task_id)
                    add_to_task_history(task)

                    # Display result files
                    if task["status"] == "COMPLETED" and task.get("result", {}).get("files"):
                        render_result_files(task["result"]["files"])

                    st.rerun()

            except Exception as e:
                st.error(f"Error polling task {task_id}: {e}")
                remove_active_task(task_id)

        # Auto-refresh for active tasks
        if active_tasks:
            time.sleep(st.session_state.get("polling_interval", 2.0))
            st.rerun()


if __name__ == "__main__":
    render()
