# Contributing to AlphaSift

Thank you for helping improve **AlphaSift**!

## Development Setup

```bash
git clone https://github.com/ZhuLinsen/alphasift.git
cd alphasift
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Never commit `.env`, API keys, webhook secrets, or `data/` run artifacts.

## Required Checks Before Opening a PR

1. Run the full test suite and linter cleanly:
   ```bash
   pytest -q
   ruff check alphasift scripts tests
   ```
2. **YAML Parity**: Every built-in strategy file under `strategies/*.yaml` MUST remain byte-for-byte identical to `alphasift/strategies/*.yaml`.
3. **Readability & Safety**:
   - Preserve deterministic L1/L2 rules and code-enforced LLM guardrails (red-flag score caps, omitted-candidate handling, secret redaction).
   - New dashboard/UI HTML must remain zero-CDN and XSS-safe (`textContent` / escaped output).
   - Document new environment variables in `.env.example` and `docs/configuration.md`.
4. **Cross-Ecosystem Alignment**: Keep `ResultSchema` changes backwards-compatible with archived `ScreenResult` JSON files and compatible with [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) & [AlphaEvo](https://github.com/ZhuLinsen/alphaevo).
