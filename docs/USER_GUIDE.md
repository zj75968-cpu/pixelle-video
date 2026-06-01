# Pixelle Video - User Guide

## Introduction
Pixelle Video is a fullstack task management system for video and image generation. This guide will help you get started with creating, monitoring, and managing tasks.

## Table of Contents
1. [Getting Started](#getting-started)
2. [Creating Tasks](#creating-tasks)
3. [Monitoring Tasks](#monitoring-tasks)
4. [Managing Results](#managing-results)
5. [Troubleshooting](#troubleshooting)
6. [Best Practices](#best-practices)

---

## Getting Started

### Accessing the Application

1. **Open your web browser**
2. **Navigate to:** `http://localhost:8501`
3. **You should see the "Create Video Task" page**

### Interface Overview

The main interface consists of:
- **Task Submission Form** - Create new tasks
- **Active Tasks Section** - Monitor running tasks
- **Task History** - View completed tasks (session-based)

---

## Creating Tasks

### Step 1: Choose Task Type

Select the type of content you want to generate:
- **VIDEO_GENERATION** - Generate video clips from text
- **IMAGE_GENERATION** - Generate images from text

### Step 2: Write Your Prompt

Enter a descriptive text prompt:

**Good Prompts:**
```
✅ "A serene sunset over a calm ocean with gentle waves"
✅ "A fluffy cat playing with a ball of yarn in slow motion"
✅ "Abstract geometric patterns in vibrant colors"
```

**Poor Prompts:**
```
❌ "video" (too vague)
❌ "" (empty)
❌ "asdfghjkl" (nonsensical)
```

**Tips for Better Prompts:**
- Be specific and descriptive
- Include details about style, mood, and composition
- Mention colors, lighting, and atmosphere
- Keep it under 500 characters for best results

### Step 3: Submit Task

1. Click the **"Submit Task"** button
2. Wait for confirmation message
3. Your task will appear in the "Active Tasks" section

**Example:**
```
Task Type: VIDEO_GENERATION
Prompt: "A peaceful forest scene with sunlight filtering through trees"

[Submit Task]
```

---

## Monitoring Tasks

### Task Status Indicators

Tasks progress through different states, indicated by colored icons:

| Icon | Status | Description |
|------|--------|-------------|
| 🟡 | PENDING | Task is queued, waiting to start |
| 🔵 | RUNNING | Task is currently processing |
| 🟢 | COMPLETED | Task finished successfully |
| 🔴 | FAILED | Task encountered an error |
| ⚫ | CANCELLED | Task was cancelled by user |

### Progress Tracking

When a task is **RUNNING**, you'll see:
- **Progress bar** showing completion percentage
- **Status message** describing current step
- **Elapsed time** since task started

**Example:**
```
🔵 RUNNING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 45.0%
45.0% - Generating frame 45/100
⏱️ 30.5s                                [Cancel]
```

### Auto-Refresh

The interface automatically refreshes every 2 seconds when you have active tasks. You don't need to manually reload the page.

### Cancelling Tasks

To cancel a running task:
1. Locate the task in "Active Tasks"
2. Click the **"Cancel"** button
3. Confirm the cancellation
4. Task status will change to ⚫ CANCELLED

**Note:** You can only cancel tasks that are PENDING or RUNNING. Completed tasks cannot be cancelled.

---

## Managing Results

### Viewing Results

When a task completes successfully, you'll see:
- ✅ **"Task completed successfully"** message
- 📁 **Result Files** section with generated content

### Result Files Section

Each result file shows:
- **File name** and **size**
- **Preview** (for videos, images, audio)
- **Download link**

**Example:**
```
📁 Result Files

output.mp4 (9.54 MB)
[Video Player Preview]
⬇️ Download

thumbnail.jpg (245.67 KB)
[Image Preview]
⬇️ Download
```

### Supported File Types

| Type | Preview | Download |
|------|---------|----------|
| Video (.mp4, .webm) | ✅ In-browser player | ✅ |
| Image (.jpg, .png) | ✅ Inline preview | ✅ |
| Audio (.mp3, .wav) | ✅ Audio player | ✅ |
| Other | ℹ️ File info only | ✅ |

### Downloading Files

1. Scroll to the "Result Files" section
2. Click the **⬇️ Download** link
3. File will download to your browser's default location

---

## Troubleshooting

### Common Issues

#### Task Stuck in PENDING
**Problem:** Task shows 🟡 PENDING for a long time

**Solutions:**
- Wait a few more seconds (tasks may queue)
- Check if backend server is running
- Refresh the page
- Cancel and resubmit the task

#### Task Failed with Error
**Problem:** Task shows 🔴 FAILED with error message

**Common Errors:**
- **"Invalid prompt format"** → Rewrite your prompt
- **"Insufficient GPU memory"** → Try shorter video duration
- **"Service unavailable"** → Backend may be overloaded, try again later

**Solutions:**
- Read the error message carefully
- Adjust your prompt or parameters
- Try a simpler task first
- Contact support if error persists

#### Can't Connect to Backend
**Problem:** "Failed to submit task: Connection refused"

**Solutions:**
1. Verify backend is running:
   ```bash
   curl http://localhost:8000/health
   ```
2. Check backend logs for errors
3. Restart backend service
4. Verify firewall settings

#### Results Not Displaying
**Problem:** Task completed but no files shown

**Solutions:**
- Refresh the page
- Check browser console for errors
- Verify file URLs are accessible
- Check backend file serving configuration

#### Page Not Refreshing
**Problem:** Task status not updating automatically

**Solutions:**
- Manually refresh the page (F5)
- Check browser console for JavaScript errors
- Clear browser cache
- Try a different browser

---

## Best Practices

### Task Management

**DO:**
- ✅ Write clear, descriptive prompts
- ✅ Monitor task progress regularly
- ✅ Cancel tasks you no longer need
- ✅ Download results promptly
- ✅ Keep task history manageable

**DON'T:**
- ❌ Submit duplicate tasks
- ❌ Leave many tasks running simultaneously
- ❌ Use extremely long prompts (>1000 chars)
- ❌ Refresh page excessively
- ❌ Submit tasks with empty prompts

### Performance Tips

1. **Limit Concurrent Tasks**
   - Run 1-3 tasks at a time for best performance
   - Wait for tasks to complete before submitting more

2. **Optimize Prompts**
   - Be specific but concise
   - Avoid unnecessary details
   - Test with simple prompts first

3. **Manage History**
   - Session history is limited to 50 tasks
   - Download important results immediately
   - Clear browser cache periodically

### Security Tips

1. **Prompt Safety**
   - Don't include personal information in prompts
   - Avoid sensitive or confidential content
   - Follow content guidelines

2. **File Downloads**
   - Scan downloaded files with antivirus
   - Verify file integrity
   - Store files securely

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl + R` | Refresh page |
| `F5` | Refresh page |
| `Ctrl + W` | Close tab |
| `Ctrl + T` | New tab |

---

## FAQ

### How long do tasks take?
- **Images:** 10-30 seconds
- **Short videos (5s):** 1-3 minutes
- **Long videos (30s+):** 5-15 minutes

Times vary based on complexity and server load.

### Can I edit a task after submission?
No, tasks cannot be edited once submitted. Cancel and create a new task instead.

### How many tasks can I run at once?
The system supports up to 10 concurrent tasks, but 1-3 is recommended for optimal performance.

### Are my tasks saved?
Task history is session-based and cleared when you close the browser. Download important results immediately.

### Can I share result files?
Yes, download files and share them as needed. Direct URLs may expire.

### What happens if I close the browser?
Active tasks continue running on the server, but you'll lose the session state. You won't be able to track them in the UI.

### Can I use the API directly?
Yes! See the [API Reference](API_REFERENCE.md) for details.

---

## Getting Help

### Support Resources
- **Documentation:** `docs/` folder
- **API Reference:** [API_REFERENCE.md](API_REFERENCE.md)
- **Deployment Guide:** [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)

### Reporting Issues
When reporting issues, include:
1. What you were trying to do
2. What happened instead
3. Error messages (if any)
4. Screenshots (if helpful)
5. Browser and OS information

### Contact
- **Email:** support@pixelle.video
- **GitHub Issues:** <repository-url>/issues
- **Documentation:** <repository-url>/docs

---

## Appendix

### Glossary

- **Task:** A unit of work (video/image generation)
- **Prompt:** Text description of desired output
- **Status:** Current state of a task
- **Progress:** Completion percentage of running task
- **Result:** Generated files from completed task
- **Session State:** Temporary storage of active tasks

### Version History

**v1.0.0 (2026-06-01)**
- Initial release
- Task creation and monitoring
- Result file display
- Session state management

---

**Last Updated:** 2026-06-01  
**Version:** 1.0.0  
**For:** Pixelle Video Task Manager
