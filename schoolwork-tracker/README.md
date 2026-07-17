# school-mcp

An MCP (Model Context Protocol) server that connects Claude to **Argo didUP** — the electronic register used by Italian schools — for one or more students. Read-only by design.

Built on [portaleargo-api](https://github.com/DTrombett/portaleargo-api), which reverse-engineers the didUP Famiglia app's API.

## What Claude can see

| Tool | Data |
|---|---|
| `list_students` | Configured students, class, school |
| `get_homework` | Assignments with due dates (from the class register) |
| `get_lesson_topics` | What was actually taught, day by day (argomenti di lezione) |
| `get_grades` | Grades with test description, teacher comment, written/oral type |
| `get_averages` | Overall / per-subject / per-month averages, written vs oral split |
| `get_notices` | Bacheca notices, flagging those needing acknowledgement or consent |
| `get_absences` | Absences and late arrivals, flagging those needing justification |
| `get_timetable` | Daily schedule with teachers |
| `get_teachers` | Class teachers with subjects and emails |
| `get_reminders` | Teacher promemoria (scheduled tests, activities) |
| `get_fees` | School payments with deadlines and status |
| `get_attachment_link` | Download URL for a notice attachment |

All tools take a `student` parameter, so one server handles multiple kids.

## Setup

```bash
npm run setup          # install + build (see note below)
cp .env.example .env   # then edit with real credentials
npm run check-login    # verifies each account logs in and prints a data summary
```

> **Why `npm run setup` instead of `npm install`?** `portaleargo-api` has no npm release, so it is installed from GitHub and must be compiled in place. Its own `postinstall` fails when installed as a dependency (its build tools aren't present), so `setup` installs with `--ignore-scripts` and then builds the library manually — including tolerating a known, harmless type error in its declaration build. Re-run `npm run setup` after any `npm install` that touches `node_modules/portaleargo-api`.

Credentials are the **native Argo didUP Famiglia** ones (school code + username + password). SPID-only accounts are not supported by the underlying login automation.

**One parent account, several children:** put the same credentials in each student's block and set `ARGO_<NAME>_STUDENT_NAME` to a substring of each child's full name as registered in Argo (case-insensitive). Argo exposes every child as a separate profile on the account; without the name filter the server would bind every student to the first profile. If you omit it on a multi-child account, startup fails with a message listing the children's names to copy from. After changing the mapping, delete `.argo-data/` so stale per-student caches are rebuilt.

## Claude Desktop configuration

Add to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
	"mcpServers": {
		"school": {
			"command": "node",
			"args": ["/home/gillus/schoolMCP/dist/index.js"]
		}
	}
}
```

Credentials are read from `.env` in the project root, so nothing sensitive goes into the Claude Desktop config. Alternatively, set the `ARGO_*` variables in the config's `env` block and skip the `.env` file.

## Notes

- **Caching**: the full Argo dashboard is fetched on first use and re-synced incrementally at most every `ARGO_SYNC_TTL_MINUTES` (default 10). Session tokens and data are persisted under `.argo-data/` (gitignored) so restarts don't re-authenticate from scratch.
- **Privacy**: everything runs locally; credentials never leave your machine except toward `portaleargo.it`. Only the data Claude explicitly requests through a tool call enters the conversation.
- **Name redaction**: set `ARGO_REDACT_NAMES=true` to replace student and teacher names with initials ("Rossi Maria" → "R.M.") in all tool output, and drop teacher emails. Name fields are always reduced to initials; free text (homework, teacher comments, notices) is scrubbed against every name the register exposes — names the server has never seen (e.g. a classmate mentioned in a note) can slip through, and attachment downloads are not scrubbed at all. For full effect also use neutral identifiers in `ARGO_STUDENTS` (e.g. `kid1`), since those appear verbatim as the `student` parameter.
- **Unofficial API**: Argo may change its API at any time. If things break, check for updates to `portaleargo-api` first.
