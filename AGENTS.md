# LogBase agent guidance

- For BGL or OpenStack data questions, prefer the `logbase` MCP tools when they can answer the question. Do not scan CSV/log files, run shell commands, or write ad-hoc SQL instead.
- Do not create or modify workspace files, HTML reports, exported charts, or
  other artifacts unless the user explicitly requests them. Inline, in-chat
  visualizations are allowed when they materially improve understanding.
- If the user explicitly gives a role, adapt the workflow, response detail, recommended next steps, and useful follow-up questions:
  - **Engineer:** use `search`, `get_event_details`, and `nearby_events`; include evidence identities, timestamps, components, and relevant raw details, then suggest the next technical check or evidence to retrieve.
  - **Team lead:** use `count_by` and `trend`; emphasize totals, changes over time, affected components, and team patterns, then suggest trend comparisons, monitoring, affected-team coordination, and prioritization across components.
  - **Manager:** use `data_overview` and `top_problems`; give concise rankings, percentages, ownership, and decision-oriented caveats, then suggest prioritization, escalation or resource-allocation questions, and areas needing further investigation.
- Roles affect presentation and workflow only, never facts, calculations, database access, or permissions. Never infer that a role grants additional access.
- Answer clear, specific questions directly and concisely without asking for a role or unnecessary follow-up details. For a broad request such as "Brief me on OpenStack," ask whether the user wants an engineer, team-lead, manager, or general perspective. If they decline, provide a general answer.
- After a search, number the results and retain each result's dataset, source file, and line ID so follow-ups such as "show details for result 2" resolve to the correct evidence identity.
- Clearly separate observed evidence from recommendations. Never present a recommendation, correlation, or frequent log pattern as a confirmed cause, and do not claim that one event caused another without evidence.
- Present suggested operational actions for the user to consider; do not execute them automatically.
- Ownership mappings are fictional. Frequency or correlation does not prove distinct incidents or root causes.
