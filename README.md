# cizhenyu_firecrawl

Firecrawl Cloud MCP for 词真语 Deploy。

## Secrets

Do **not** put API keys in this repo.

Deploy injects:

- `CIZHENYU_AUTH_DIR` → `firecrawl.json` (`apiKey`)
- and/or process env `FIRECRAWL_API_KEY`

## Run

```bash
python server.py
```
