"""Session state management for tasks"""
import streamlit as st


def init_task_state():
    """Initialize task-related session state"""
    if "active_tasks" not in st.session_state:
        st.session_state["active_tasks"] = []

    if "task_history" not in st.session_state:
        st.session_state["task_history"] = []

    if "polling_interval" not in st.session_state:
        st.session_state["polling_interval"] = 2.0  # seconds


def add_active_task(task_id: str):
    """
    Add task to active tasks list.

    Args:
        task_id: Task identifier
    """
    if "active_tasks" not in st.session_state:
        init_task_state()

    if task_id not in st.session_state["active_tasks"]:
        st.session_state["active_tasks"].append(task_id)


def remove_active_task(task_id: str):
    """
    Remove task from active tasks list.

    Args:
        task_id: Task identifier
    """
    if "active_tasks" in st.session_state:
        if task_id in st.session_state["active_tasks"]:
            st.session_state["active_tasks"].remove(task_id)


def add_to_task_history(task: dict):
    """
    Add completed task to history.

    Args:
        task: Task dict to add to history
    """
    if "task_history" not in st.session_state:
        init_task_state()

    # Keep only last 50 tasks
    st.session_state["task_history"].insert(0, task)
    if len(st.session_state["task_history"]) > 50:
        st.session_state["task_history"] = st.session_state["task_history"][:50]


def get_active_tasks() -> list:
    """
    Get list of active task IDs.

    Returns:
        List of active task IDs
    """
    if "active_tasks" not in st.session_state:
        init_task_state()
    return st.session_state["active_tasks"]


def get_task_history() -> list:
    """
    Get task history.

    Returns:
        List of completed tasks (most recent first)
    """
    if "task_history" not in st.session_state:
        init_task_state()
    return st.session_state["task_history"]
