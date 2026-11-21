## Summary
Describe the change and which problem or issue it addresses.

## Type of Change
- [ ] Strategy / scoring / risk improvement (kept deterministic rules & red-flag guardrails)
- [ ] Data source / daily pack / MCP / Web UI / Docker / CI fix
- [ ] Documentation / i18n update

## Checklist
- [ ] `pytest -q` passes locally
- [ ] `ruff check alphasift scripts tests` passes with zero errors
- [ ] `strategies/*.yaml` and `alphasift/strategies/*.yaml` remain byte-for-byte identical
- [ ] No secrets, `.env`, or `data/` artifacts committed
