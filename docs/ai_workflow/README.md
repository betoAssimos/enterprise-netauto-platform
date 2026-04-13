# AI Workflow System

AI collaboration system for the Enterprise Network Automation Platform.
Owner: Alberto Assimos (Beto) — v1.0 — 2026-04-13

This directory contains everything needed to work with Claude as a
structured engineering partner across study, lab, and review sessions.

---

## What This Is Not

This is not automation code. It is not part of the FastMCP server.
The `ai/` directory holds production implementation code (MCP server,
LangChain agent, Ollama integration). This directory holds the
human-AI collaboration system: operating procedures, context files,
memory templates, and audit trails.

---

## File Map

```
docs/ai-workflow/
├── README.md               you are here — system index
├── daily_procedure.md      how to operate every session
├── session_wrapper.md      copy-paste this to start every Claude session
├── master_context.md       long-term brain — attach to high-stakes sessions
├── gait_audit.md           append-only AI behavior log
└── templates/
    ├── session_memory.md   blank template — copy per session
    └── decision_record.md  blank template — copy per decision

docs/sessions/              completed session logs
    YYYY-MM-DD_topic.md

docs/decisions/             architecture decision records
    DR-NNN_short_name.md
```

---

## Quick Start

1. Read `daily_procedure.md` once — it defines the operating model
2. Open `session_wrapper.md` and fill in the three variables at the top
3. Paste the entire file into a new Claude conversation
4. Claude confirms the goal — you confirm back — work begins

---

## Maintenance

| Action | When | File |
|--------|------|------|
| Start session | Every session | session_wrapper.md |
| Log session | End of every session | templates/session_memory.md → docs/sessions/ |
| Record a decision | When architecture changes | templates/decision_record.md → docs/decisions/ |
| Update AI behavior log | End of every session | gait_audit.md (append) |
| Full consolidation | Weekly | All files → update master_context.md |

---

## Version History

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-04-13 | Initial creation |