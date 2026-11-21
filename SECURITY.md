# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| `0.3.x` | Yes       |
| `< 0.3` | Security fixes backported selectively |

## Reporting a Vulnerability

Please **do not** open a public GitHub Issue for security vulnerabilities, credential leaks, or SSRF/XSS/path-traversal reports.

Instead, report privately via [GitHub Security Advisories](https://github.com/ZhuLinsen/alphasift/security/advisories/new) with:
- Component / file path affected (`alphasift/server.py`, `alphasift/mcp.py`, `alphasift/llm_client.py`, `alphasift/notify.py`, GitHub Actions workflow, etc.)
- Minimal reproduction steps and security impact

We aim to acknowledge reports within 48 hours and publish fixes promptly.

## Built-In Security Boundaries

- **Local HTTP Workbench (`alphasift serve`)**: Read-only GET endpoints bind `127.0.0.1` by default, validate `run=` references inside `data/runs/`, pattern scans against the built-in catalog, and `detail_url` against `http(s)` / safe relative URLs, disable paid LLM calls on GET `/daily-report`, omit wildcard CORS headers (`same-origin` default), and send `CSP` (hashed script execution), `X-Content-Type-Options: nosniff`, and `X-Frame-Options: DENY`. Note that explicit `?live=1` on diagnostic endpoints triggers outbound source health probes against public market endpoints.
- **STDIO MCP Server (`alphasift mcp`)**: Locks pattern names to built-in catalog entries, enforces strict schema validation (`additionalProperties: false`), and keeps stdout dedicated exclusively to JSON-RPC frames.
- **LLM & IM Secrets**: Multi-channel credentials without explicit channel keys do not inherit unrelated ambient provider keys, custom endpoints block embedded URL userinfo/query/fragment delimiters and HTTP redirects, and webhook tokens/keys are stripped before error logs (`notify.py`). Notice that explicit `LLM_BASE_URL` / `OPENAI_BASE_URL` overrides on direct provider models remain an intentional operator relay setting.
