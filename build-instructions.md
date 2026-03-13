# Claude Code Prompt — Task Coach MVP

Paste this into Claude Code to kick off the build.

---

Build me a personal task coach web app called "Cockpit". This is an MVP — keep it lean, functional, and shippable. I want to deploy this on Railway with a database so I can access it from my phone and laptop.

## Stack

- **Backend:** Python Flask
- **Database:** PostgreSQL (for Railway deployment; use SQLAlchemy so I can swap to SQLite locally during dev)
- **Frontend:** Server-side rendered with Jinja2 templates + Tailwind CSS (CDN is fine for MVP) + vanilla JS for interactivity (no React)
- **AI:** Anthropic Claude API (claude-sonnet-4-20250514) via the anthropic Python SDK
- **Auth:** Simple PIN or password login (single user app, no need for full auth system). Protect all routes.

## Core Data Model

### Tasks
- id, title, description
- status: not_started, in_progress, blocked, done, archived
- priority: low, medium, high, critical
- size: S, M, L (estimated effort)
- deadline (optional date)
- deliverable (text — what "done" looks like)
- reporting_to (text — who this is for)
- waiting_on (text — who/what is blocking this)
- product_area (text — for grouping, e.g. "LIMCA 3", "ALNEXT2", "Personal")
- created_at, updated_at, completed_at
- sort_order (integer, for manual reordering)

### DailyCheckIn
- id, date
- energy_level: low, medium, high
- time_available (text, e.g. "Full day", "2hr block then meetings")
- meetings (text)
- blockers (text)
- notes (text — what's on my mind, carry-over from yesterday)

### ChatMessage
- id, task_id (nullable — null means it's a general planning chat, non-null means it's a task-specific conversation)
- role: user, assistant
- content (text)
- created_at

## Pages / Routes

### 1. Dashboard (/)
The main view. This is where I live all day. Show:
- **Today's check-in status** at the top — either a filled summary or a prompt to fill it out
- **Active tasks** grouped by status (in_progress first, then not_started, then blocked), with colored status badges
- **Quick actions:** Mark done, mark blocked, start task — all without leaving the page (use htmx or fetch calls)
- **Completed today** section at the bottom — show tasks I finished today as a win list
- **Floating chat button** in the bottom-right corner that opens the general planning chat

### 2. Daily Check-In (/checkin)
- A simple form with the fields from DailyCheckIn
- Pre-fills with today's check-in if it exists (edit mode)
- After saving, redirect to dashboard

### 3. Task Detail (/task/<id>)
- Full task view with all fields, editable inline or via a form
- **Task-specific chat panel** below the task details — this is a conversation with Claude specifically about THIS task. The chat has the task's full context (title, description, deliverable, status, deadline, etc.) injected into the system prompt so Claude can help me work through it.
- Chat input at the bottom

### 4. New Task (/task/new)
- Simple form. Only title is required, everything else is optional.
- After creation, redirect to task detail page.

### 5. General Planning Chat (/chat)
- Full-page chat interface for discussing priorities, planning my day, thinking through problems
- The system prompt includes: my current task list summary (titles, statuses, deadlines, sizes), today's check-in data, and the task coach instructions
- Claude can suggest creating tasks, reprioritizing, etc. — but for MVP, I'll do those actions manually. Don't build function calling yet.

### 6. Archive (/archive)
- List of completed/archived tasks with completion dates. Simple table view. Searchable.

## AI System Prompts

### General Planning Chat System Prompt
```
You are my personal task coach and accountability partner. You have full context on my current workload and state of mind.

Here is my current check-in for today:
{today's check-in data or "No check-in submitted yet today."}

Here is my current task list:
{formatted list of all active tasks with: title, status, priority, size, deadline, product_area, waiting_on}

Rules:
- Give me one task at a time when I ask what to do next
- Match task difficulty to my energy level and available time
- Prioritize: deadlines > blocking others > quick wins when low energy > deep work when high energy
- Keep responses short and direct unless I ask for detail
- When I say "done" with something, celebrate briefly and give me the next thing
- When I say "stuck", help me break it down or suggest timeboxing
- When I say "how am I doing", give me a completed vs remaining tally
- If I'm avoiding something, gently call it out
- Be warm but direct. Think coach, not assistant.
```

### Task-Specific Chat System Prompt
```
You are helping me work through a specific task. Here is the full context:

Title: {title}
Description: {description}
Status: {status}
Priority: {priority}
Size: {size}
Deadline: {deadline}
Deliverable: {deliverable}
Reporting to: {reporting_to}
Waiting on: {waiting_on}
Product area: {product_area}

Help me think through and execute this task. You can:
- Help me break it into subtasks
- Draft documents, emails, or plans related to it
- Think through blockers or decisions
- Suggest next steps

Keep responses practical and focused on getting this task done.
```

## UI / Design

- **Mobile-first responsive design** — I'll use this on my phone too
- Clean, minimal look. Light background, subtle borders, readable typography.
- Use Tailwind utility classes. No custom CSS unless absolutely necessary.
- Color-code task statuses: not_started (gray), in_progress (blue), blocked (amber/yellow), done (green)
- Priority indicators: critical (red dot), high (orange dot), medium (blue dot), low (gray dot)
- The chat interfaces should feel like a messaging app — messages stacked vertically, user messages right-aligned, assistant messages left-aligned
- **Dark mode not needed for MVP**

## Technical Requirements

- Use Flask blueprints to organize routes (main, tasks, chat, checkin)
- Store the Anthropic API key in an environment variable (ANTHROPIC_API_KEY)
- Store the app PIN/password in an environment variable (APP_PIN)
- Include a requirements.txt and a Procfile for Railway deployment
- Include a .env.example file
- Use Flask-Migrate for database migrations
- Chat should stream Claude's responses if feasible, otherwise just show a loading spinner and render the complete response
- Rate-limit API calls sensibly — add a small delay or debounce on the chat send button to prevent double-sends
- All times should display in Eastern Time (America/Toronto)

## What NOT to build (MVP scope control)
- No drag-and-drop reordering (just manual sort_order field for now)
- No subtasks (just use the task chat to break things down)
- No notifications or reminders
- No calendar integration
- No file attachments
- No function calling / tool use with Claude (just chat)
- No recurring tasks
- No multi-user support
- No fancy animations

## File Structure
```
cockpit/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── models.py            # SQLAlchemy models
│   ├── blueprints/
│   │   ├── main.py          # Dashboard, auth
│   │   ├── tasks.py         # Task CRUD
│   │   ├── chat.py          # Chat routes + AI
│   │   └── checkin.py       # Daily check-in
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── task_detail.html
│   │   ├── task_form.html
│   │   ├── chat.html
│   │   ├── checkin.html
│   │   └── archive.html
│   └── static/              # Minimal, mostly Tailwind handles it
├── migrations/
├── .env.example
├── requirements.txt
├── Procfile
├── config.py
└── run.py
```

## Getting Started

Set up the project, create the database models, run migrations, and build out the pages one at a time starting with: models → auth → dashboard → task CRUD → daily check-in → chat (general) → chat (task-specific) → archive.

Test each piece as you go. Use SQLite locally for development (DATABASE_URL=sqlite:///cockpit.db) and PostgreSQL on Railway.
