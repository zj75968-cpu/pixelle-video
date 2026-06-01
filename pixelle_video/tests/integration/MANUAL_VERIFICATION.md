# Integration Testing Manual Verification Checklist

## Phase 3: Integration Testing

### Automated Tests Status
- ✅ End-to-end happy path tests
- ✅ Error scenario tests

### Manual Verification Checklist

#### 1. Backend API Verification
- [ ] Start backend server: `python -m pixelle_video.api.main`
- [ ] Verify server starts on http://localhost:8000
- [ ] Check API docs at http://localhost:8000/docs
- [ ] Test POST /api/tasks endpoint manually
- [ ] Test GET /api/tasks/{task_id} endpoint manually
- [ ] Test DELETE /api/tasks/{task_id} endpoint manually

#### 2. Frontend UI Verification
- [ ] Start Streamlit app: `streamlit run pixelle_video/web/views/create_page.py`
- [ ] Verify app loads without errors
- [ ] Check page title and layout render correctly

#### 3. Task Submission Flow
- [ ] Fill in task form with valid prompt
- [ ] Select task type (VIDEO_GENERATION or IMAGE_GENERATION)
- [ ] Click "Submit Task" button
- [ ] Verify success message appears with task_id
- [ ] Verify task appears in "Active Tasks" section

#### 4. Task Status Polling
- [ ] Verify task status updates automatically (every 2 seconds)
- [ ] Check status indicator changes: 🟡 PENDING → 🔵 RUNNING → 🟢 COMPLETED
- [ ] Verify progress bar appears when status is RUNNING
- [ ] Verify progress percentage and message update correctly
- [ ] Check elapsed time counter updates

#### 5. Task Cancellation
- [ ] Submit a long-running task
- [ ] Click "Cancel" button while task is RUNNING
- [ ] Verify cancellation confirmation message
- [ ] Verify task status changes to ⚫ CANCELLED
- [ ] Verify task moves from active to history

#### 6. Result Display
- [ ] Wait for task to complete
- [ ] Verify "Task completed successfully" message
- [ ] Check "📁 Result Files" section appears
- [ ] Verify file information displays (name, size, type)
- [ ] For video files: verify video player renders
- [ ] For image files: verify image preview renders
- [ ] Click download link and verify file downloads

#### 7. Multiple Tasks
- [ ] Submit 3 tasks in quick succession
- [ ] Verify all 3 appear in "Active Tasks"
- [ ] Verify each task polls independently
- [ ] Verify tasks complete and move to history independently
- [ ] Check no task status gets mixed up

#### 8. Error Handling
- [ ] Submit task with empty prompt → verify error message
- [ ] Stop backend server → submit task → verify connection error
- [ ] Submit task → manually delete task via API → verify 404 handling
- [ ] Submit invalid task_type via API → verify 400 error handling

#### 9. Session State Persistence
- [ ] Submit task and let it run
- [ ] Refresh browser page
- [ ] Verify active tasks are lost (expected - session state is not persistent)
- [ ] Verify task history is lost (expected)
- [ ] Note: This is current behavior, persistence would require backend storage

#### 10. UI/UX Quality
- [ ] Check responsive layout on different window sizes
- [ ] Verify colors and icons are consistent
- [ ] Check text is readable and properly formatted
- [ ] Verify no console errors in browser dev tools
- [ ] Check auto-refresh doesn't cause UI flicker

#### 11. Performance
- [ ] Submit 10 tasks and monitor CPU/memory usage
- [ ] Verify polling doesn't cause performance degradation
- [ ] Check network requests are efficient (no duplicate calls)
- [ ] Verify UI remains responsive during polling

#### 12. Edge Cases
- [ ] Submit task with very long prompt (1000+ characters)
- [ ] Submit task with special characters in prompt
- [ ] Let task run for extended period (5+ minutes)
- [ ] Submit task, close browser, reopen → verify state is reset
- [ ] Test with slow network (throttle in dev tools)

### Test Results Summary

#### Automated Tests
```bash
# Run all integration tests
pytest tests/integration/ -v

# Expected results:
# - test_e2e_happy_path.py: 3 tests
# - test_error_scenarios.py: 9 tests
# Total: 12 tests
```

#### Manual Tests
- Total checks: 50+
- Completed: [ ] / 50+
- Issues found: [ ]
- Issues resolved: [ ]

### Known Limitations
1. Session state is not persistent across browser refreshes
2. No authentication/authorization implemented
3. No rate limiting on API calls
4. File downloads require backend file serving (not implemented yet)
5. No real video generation - backend returns mock responses

### Next Steps After Verification
1. Document any issues found during manual testing
2. Fix critical bugs before Phase 4
3. Update user documentation with verified workflows
4. Prepare deployment checklist
