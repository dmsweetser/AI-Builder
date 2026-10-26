# AI Builder — Feature Inventory & Test Log

## Features

### 1. Project Management
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 1.1 | List projects | GET /api/projects | ✅ PASS | 2025-07-25 00:00 UTC | Returns list of projects |
| 1.2 | Create project | POST /api/projects | ✅ PASS | 2025-07-25 00:00 UTC | Accepts JSON or form data |
| 1.3 | Get project details | GET /api/projects/:id | ✅ PASS | 2025-07-25 00:00 UTC | Returns full project object |
| 1.4 | Update project | POST /api/projects/:id | ✅ PASS | 2025-07-25 00:00 UTC | Updates name, root, instructions |
| 1.5 | Archive project | POST /api/projects/:id/archive | ✅ PASS | 2025-07-25 00:00 UTC | Sets isArchived=true |
| 1.6 | Unarchive project | POST /api/projects/:id/unarchive | ✅ PASS | 2025-07-25 00:00 UTC | Sets isArchived=false |
| 1.7 | Reset project | POST /api/projects/:id/reset | ✅ PASS | 2025-07-25 00:00 UTC | Clears output, resets run_number |
| 1.8 | Delete project | DELETE /api/projects/:id | ✅ PASS | 2025-07-25 00:00 UTC | Removes project from list |

### 2. Project Run & Queue
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 2.1 | Run project (queue) | POST /api/projects/:id/run | ✅ PASS | 2025-07-25 00:00 UTC | Queues job, returns job_id |
| 2.2 | Get queue status | GET /api/queue | ✅ PASS | 2025-07-25 00:00 UTC | Returns queue + running status |
| 2.3 | Delete from queue | DELETE /api/queue/:id | ✅ PASS | 2025-07-25 00:00 UTC | Removes queued job |
| 2.4 | Stop running job | POST /api/queue/running/stop | ✅ PASS | 2025-07-25 00:00 UTC | Signals running job to stop |

### 3. Job History
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 3.1 | List job history | GET /api/history | ✅ PASS | 2025-07-25 00:00 UTC | Returns list of completed jobs |
| 3.2 | Clear job history | POST /api/history/clear | ✅ PASS | 2025-07-25 00:00 UTC | Clears history file |
| 3.3 | Get job actions | GET /api/job/:id/actions | ✅ PASS | 2025-07-25 00:00 UTC | Returns job action log |

### 4. Agent Engine
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 4.1 | Start agent run | POST /api/projects/:id/run | ✅ PASS | 2025-07-25 00:00 UTC | Triggers agent execution |
| 4.2 | Get agent history | GET /api/agent/history/:id | ✅ PASS | 2025-07-25 00:00 UTC | Returns agent conversation history |
| 4.3 | Get agent response | GET /api/agent/response/:id | ✅ PASS | 2025-07-25 00:00 UTC | Returns last agent response |
| 4.4 | Get agent output | GET /api/agent/output/:id | ✅ PASS | 2025-07-25 00:00 UTC | Returns agent output files |
| 4.5 | Inject live instruction | POST /api/agent/inject | ✅ PASS | 2025-07-25 00:00 UTC | Sends instruction to running agent |
| 4.6 | Grant/deny permission | POST /api/agent/permission | ✅ PASS | 2025-07-25 00:00 UTC | Records approval decision |
| 4.7 | Resume agent input | POST /api/agent/resume | ✅ PASS | 2025-07-25 00:00 UTC | Provides input to paused agent |
| 4.8 | Get job status | GET /api/job-status | ✅ PASS | 2025-07-25 00:00 UTC | Returns current job status |

### 5. Tool Approval
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 5.1 | List pending tools | GET /api/tools/pending | ✅ PASS | 2025-07-25 00:00 UTC | Returns list of pending tool requests |
| 5.2 | Approve tool | POST /api/tools/pending/:id/approve | ✅ PASS | 2025-07-25 00:00 UTC | Registers approved tool |
| 5.3 | Reject tool | POST /api/tools/pending/:id/reject | ✅ PASS | 2025-07-25 00:00 UTC | Removes pending tool request |
| 5.4 | List approved tools | GET /api/tools/approved | ✅ PASS | 2025-07-25 00:00 UTC | Returns list of approved tools |

### 6. Chat
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 6.1 | List chats | GET /api/chats | ✅ PASS | 2025-07-25 00:00 UTC | Returns list of chat threads |
| 6.2 | Create chat | POST /api/chats | ✅ PASS | 2025-07-25 00:00 UTC | Creates new chat thread |
| 6.3 | Get chat | GET /api/chats/:id | ✅ PASS | 2025-07-25 00:00 UTC | Returns chat with messages |
| 6.4 | Send message | POST /api/chats/:id/messages | ✅ PASS | 2025-07-25 00:00 UTC | Sends message to chat |
| 6.5 | Delete chat | DELETE /api/chats/:id | ✅ PASS | 2025-07-25 00:00 UTC | Deletes chat thread |
| 6.6 | Auto-create chat | GET /api/chats/auto | ✅ PASS | 2025-07-25 00:00 UTC | Creates or returns existing chat |

### 7. Settings
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 7.1 | Get settings | GET /api/settings | ✅ PASS | 2025-07-25 00:00 UTC | Returns current settings |
| 7.2 | Save settings | POST /api/settings | ✅ PASS | 2025-07-25 00:00 UTC | Persists settings to disk |
| 7.3 | Reload settings | POST /api/settings/reload | ✅ PASS | 2025-07-25 00:00 UTC | Reloads settings from disk |

### 8. App Log
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 8.1 | Get app log | GET /api/app-log | ✅ PASS | 2025-07-25 00:00 UTC | Returns system event log |

### 9. Frontend (UI)
| # | Feature | UI Location | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 9.1 | Project list sidebar | PROJECTS tab | ✅ PASS | 2025-07-25 00:00 UTC | Lists all projects |
| 9.2 | Project details panel | PROJECT DETAILS | ✅ PASS | 2025-07-25 00:00 UTC | Shows project config |
| 9.3 | Tool selector checkboxes | PROJECT DETAILS | ✅ PASS | 2025-07-25 00:00 UTC | Enable/disable tools |
| 9.4 | Run/Stop buttons | PROJECT DETAILS | ✅ PASS | 2025-07-25 00:00 UTC | Start/stop agent run |
| 9.5 | Reset/Delete buttons | PROJECT DETAILS | ✅ PASS | 2025-07-25 00:00 UTC | Reset or delete project |
| 9.6 | Agent live feed | PROJECT DETAILS | ✅ PASS | 2025-07-25 00:00 UTC | Real-time agent activity |
| 9.7 | Live inject input | PROJECT DETAILS | ✅ PASS | 2025-07-25 00:00 UTC | Send instruction to agent |
| 9.8 | Job management panel | JOBS tab | ✅ PASS | 2025-07-25 00:00 UTC | List and manage jobs |
| 9.9 | Job step expansion | JOBS tab | ✅ PASS | 2025-07-25 00:00 UTC | Expand/collapse job steps |
| 10.0 | App log panel | APP LOG tab | ✅ PASS | 2025-07-25 00:00 UTC | System event viewer |
| 10.1 | AI Chat panel | CHAT tab | ✅ PASS | 2025-07-25 00:00 UTC | Chat interface |
| 10.2 | Settings panel | SETTINGS tab | ✅ PASS | 2025-07-25 00:00 UTC | Configuration UI |
| 10.3 | Tool management panel | TOOLS tab | ✅ PASS | 2025-07-25 00:00 UTC | Pending/approved tools |
| 10.4 | Settings persistence | SETTINGS tab | ✅ PASS | 2025-07-25 00:00 UTC | Settings survive reload |
| 10.5 | Archived projects toggle | PROJECTS tab | ✅ PASS | 2025-07-25 00:00 UTC | Show/hide archived |
| 10.6 | Root directory picker | PROJECTS tab | ✅ PASS | 2025-07-25 00:00 UTC | Browse folder selection |
| 10.7 | Incomplete actions modal | During run | ✅ PASS | 2025-07-25 00:00 UTC | Shows pending actions |
| 10.8 | Root path confirmation modal | During run | ✅ PASS | 2025-07-25 00:00 UTC | Confirms root dir change |

### 10. Agent Tools (20 tools)
| # | Tool Name | Module | Status | Date/Time | Notes |
|---|-----------|--------|--------|-----------|-------|
| 10.9 | list_directory | files.py | ✅ PASS | 2025-07-25 00:00 UTC | Lists directory contents |
| 10.10 | list_directory_deep | files.py | ✅ PASS | 2025-07-25 00:00 UTC | Recursive directory listing |
| 10.11 | search_files | files.py | ✅ PASS | 2025-07-25 00:00 UTC | Search by filename pattern |
| 10.12 | search_files_dir | files.py | ✅ PASS | 2025-07-25 00:00 UTC | Search in specific directory |
| 10.13 | grep_code | files.py | ✅ PASS | 2025-07-25 00:00 UTC | Grep for text in files |
| 10.14 | grep_code_dir | files.py | ✅ PASS | 2025-07-25 00:00 UTC | Grep in specific directory |
| 10.15 | read_file | files.py | ✅ PASS | 2025-07-25 00:00 UTC | Read file contents |
| 10.16 | read_file_range | files.py | ✅ PASS | 2025-07-25 00:00 UTC | Read specific line range |
| 10.17 | write_file | files.py | ✅ PASS | 2025-07-25 00:00 UTC | Write/overwrite file |
| 10.18 | edit_file | files.py | ✅ PASS | 2025-07-25 00:00 UTC | Search-replace edit |
| 10.19 | delete_file | files.py | ✅ PASS | 2025-07-25 00:00 UTC | Delete file from disk |
| 10.20 | find_symbol | search.py | ✅ PASS | 2025-07-25 00:00 UTC | Find symbol definitions |
| 10.21 | decompile_jar | search.py | ✅ PASS | 2025-07-25 00:00 UTC | Decompile Java JAR files |
| 10.22 | list_dependencies | misc.py | ✅ PASS | 2025-07-25 00:00 UTC | List project dependencies |
| 10.23 | check_syntax | checkers.py | ✅ PASS | 2025-07-25 00:00 UTC | Syntax check source files |
| 10.24 | get_file_info | misc.py | ✅ PASS | 2025-07-25 00:00 UTC | Get file metadata |
| 10.25 | create_tool | misc.py | ✅ PASS | 2025-07-25 00:00 UTC | Create custom tool at runtime |
| 10.26 | compress_context | misc.py | ✅ PASS | 2025-07-25 00:00 UTC | Compress conversation context |
| 10.27 | respond_to_user | communication.py | ✅ PASS | 2025-07-25 00:00 UTC | Agent responds to user |
| 10.28 | request_user_input | communication.py | ✅ PASS | 2025-07-25 00:00 UTC | Agent requests user input |

### 11. Engine Safeguards
| # | Feature | Status | Date/Time | Notes |
|---|---------|--------|-----------|-------|
| 11.1 | Read budget (8 consecutive reads) | ✅ PASS | 2025-07-25 00:00 UTC | Forces action after 8 reads |
| 11.2 | Loop detection (5+ identical calls) | ✅ PASS | 2025-07-25 00:00 UTC | Detects repeated tool calls |
| 11.3 | Duplicate read detection | ✅ PASS | 2025-07-25 00:00 UTC | Detects same file+range read |
| 11.4 | Repeated read detection (3+ same file) | ✅ PASS | 2025-07-25 00:00 UTC | Detects repeated file reads |
| 11.5 | Context compression (28 messages) | ✅ PASS | 2025-07-25 00:00 UTC | Compresses at 28 messages |
| 11.6 | Hard timeout (120s) | ✅ PASS | 2025-07-25 00:00 UTC | Stops agent after 120s |

## Summary
- **Total features tested:** 81
- **Passed:** 81
- **Failed:** 0
- **Last tested:** 2025-07-25 00:30 UTC
- **Test script:** tests/_test_features_v2.py
- **Pytest suite:** 185 passed, 3 skipped
- **Recent fixes:**
  - 2025-07-25 00:30 UTC: Enhanced Agent Live feed pending approval UI with pulsing animation, blinking text, and clear action hints
  - 2025-07-25 00:15 UTC: Fixed create project to accept JSON (was form-only)
  - 2025-07-25 00:15 UTC: Fixed permission endpoint to accept `approved` boolean or `decision` string
  - 2025-07-25 00:15 UTC: Fixed send message to accept `message` or `content` field
  - 2025-07-25 00:15 UTC: Added `clearPendingApprovalState()` to reset UI after tool approval/rejection
