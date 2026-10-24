# AI Builder — Feature Inventory & Test Log

## Features

### 1. Project Management
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 1.1 | List projects | GET /api/projects | | | |
| 1.2 | Create project | POST /api/projects | | | |
| 1.3 | Get project details | GET /api/projects/:id | | | |
| 1.4 | Update project | POST /api/projects/:id | | | |
| 1.5 | Archive project | POST /api/projects/:id/archive | | | |
| 1.6 | Unarchive project | POST /api/projects/:id/unarchive | | | |
| 1.7 | Reset project | POST /api/projects/:id/reset | | | |
| 1.8 | Delete project | DELETE /api/projects/:id | | | |

### 2. Project Run & Queue
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 2.1 | Run project (queue) | POST /api/projects/:id/run | | | |
| 2.2 | Get queue status | GET /api/queue | | | |
| 2.3 | Delete from queue | DELETE /api/queue/:id | | | |
| 2.4 | Stop running job | POST /api/queue/running/stop | | | |

### 3. Job History
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 3.1 | List job history | GET /api/history | | | |
| 3.2 | Clear job history | POST /api/history/clear | | | |
| 3.3 | Get job actions | GET /api/job/:id/actions | | | |

### 4. Agent Engine
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 4.1 | Start agent run | POST /api/agent/run | | | |
| 4.2 | Get agent history | GET /api/agent/history/:id | | | |
| 4.3 | Get agent response | GET /api/agent/response/:id | | | |
| 4.4 | Get agent output | GET /api/agent/output/:id | | | |
| 4.5 | Inject live instruction | POST /api/agent/inject | | | |
| 4.6 | Grant/deny permission | POST /api/agent/permission | | | |
| 4.7 | Resume agent input | POST /api/agent/resume | | | |
| 4.8 | Get job status | GET /api/job-status | | | |

### 5. Tool Approval
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 5.1 | List pending tools | GET /api/tools/pending | | | |
| 5.2 | Approve tool | POST /api/tools/pending/:id/approve | | | |
| 5.3 | Reject tool | POST /api/tools/pending/:id/reject | | | |
| 5.4 | List approved tools | GET /api/tools/approved | | | |

### 6. Chat
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 6.1 | List chats | GET /api/chats | | | |
| 6.2 | Create chat | POST /api/chats | | | |
| 6.3 | Get chat | GET /api/chats/:id | | | |
| 6.4 | Send message | POST /api/chats/:id/messages | | | |
| 6.5 | Delete chat | DELETE /api/chats/:id | | | |
| 6.6 | Auto-create chat | GET /api/chats/auto | | | |

### 7. Settings
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 7.1 | Get settings | GET /api/settings | | | |
| 7.2 | Save settings | POST /api/settings | | | |
| 7.3 | Reload settings | POST /api/settings/reload | | | |

### 8. App Log
| # | Feature | API Endpoint | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 8.1 | Get app log | GET /api/app-log | | | |

### 9. Frontend (UI)
| # | Feature | UI Location | Status | Date/Time | Notes |
|---|---------|-------------|--------|-----------|-------|
| 9.1 | Project list sidebar | PROJECTS tab | | | |
| 9.2 | Project details panel | PROJECT DETAILS | | | |
| 9.3 | Tool selector checkboxes | PROJECT DETAILS | | | |
| 9.4 | Run/Stop buttons | PROJECT DETAILS | | | |
| 9.5 | Reset/Delete buttons | PROJECT DETAILS | | | |
| 9.6 | Agent live feed | PROJECT DETAILS | | | |
| 9.7 | Live inject input | PROJECT DETAILS | | | |
| 9.8 | Job management panel | JOBS tab | | | |
| 9.9 | Job step expansion | JOBS tab | | | |
| 10.0 | App log panel | APP LOG tab | | | |
| 10.1 | AI Chat panel | CHAT tab | | | |
| 10.2 | Settings panel | SETTINGS tab | | | |
| 10.3 | Tool management panel | TOOLS tab | | | |
| 10.4 | Settings persistence | SETTINGS tab | | | |
| 10.5 | Archived projects toggle | PROJECTS tab | | | |
| 10.6 | Root directory picker | PROJECTS tab | | | |
| 10.7 | Incomplete actions modal | During run | | | |
| 10.8 | Root path confirmation modal | During run | | | |

### 10. Agent Tools (22 tools)
| # | Tool Name | Module | Status | Date/Time | Notes |
|---|-----------|--------|--------|-----------|-------|
| 10.9 | list_directory | files.py | | | |
| 10.10 | list_directory_deep | files.py | | | |
| 10.11 | search_files | files.py | | | |
| 10.12 | search_files_dir | files.py | | | |
| 10.13 | grep_code | files.py | | | |
| 10.14 | grep_code_dir | files.py | | | |
| 10.15 | read_file | files.py | | | |
| 10.16 | read_file_range | files.py | | | |
| 10.17 | write_file | files.py | | | |
| 10.18 | edit_file | files.py | | | |
| 10.19 | delete_file | files.py | | | |
| 10.20 | find_symbol | search.py | | | |
| 10.21 | decompile_jar | search.py | | | |
| 10.22 | list_dependencies | misc.py | | | |
| 10.23 | check_syntax | checkers.py | | | |
| 10.24 | get_file_info | misc.py | | | |
| 10.25 | create_tool | misc.py | | | |
| 10.26 | compress_context | misc.py | | | |
| 10.27 | respond_to_user | communication.py | | | |
| 10.28 | request_user_input | communication.py | | | |

### 11. Engine Safeguards
| # | Feature | Status | Date/Time | Notes |
|---|---------|--------|-----------|-------|
| 11.1 | Read budget (8 consecutive reads) | | | |
| 11.2 | Loop detection (5+ identical calls) | | | |
| 11.3 | Duplicate read detection | | | |
| 11.4 | Repeated read detection (3+ same file) | | | |
| 11.5 | Context compression (28 messages) | | | |
| 11.6 | Hard timeout (120s) | | | |
