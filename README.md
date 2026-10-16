# Making Sense of Logs: SereneDB Challenge

National AI Hackathon 2026 (SchubKI), SereneDB challenge.

An MCP server that lets an AI agent (Claude) investigate system logs stored in SereneDB and answer questions for three roles: **Engineer**, **Team Lead** and **Manager**.

**Workflow:** question → evidence (SereneDB queries) → recommendation

## Data
- BGL (supercomputer logs)
- OpenStack (cloud logs)
- Team-ownership table (maps components to teams)

Source: Loghub (Zhu et al., ISSRE 2023; BGL also Oliner & Stearley, DSN 2007).

## Setup
1. Clone this repo and create a virtual environment:
   `python -m venv .venv` and activate it
2. Install dependencies: `pip install -r requirements.txt`
...

## Tools
| Tool | Purpose | Inputs | Output |
|---|---|---|---|
| `<tool name>` | `<what it does>` | `<inputs>` | `<output>` |

...
