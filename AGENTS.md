# Discord Skill (for sibling agents)

Minimal `discord` CLI — read Discord messages via REST API.

Use this CLI first for read-only Discord work. Browser, OpenCLI, DOM scraping,
Discord Desktop CDP, and MCP are fallback routes only when REST cannot answer
the request.

```bash
discord fetch    <channel>  [--days N | --hours N] [--author NAME] [--out PATH]
discord search   <guild>    "QUERY" [--channel CH] [--author-id ID] [--days N]
discord channels
discord status
discord setup
```

`<channel>` / `<guild>` accept aliases from `~/.config/discord-cli/channels.yaml`
or raw numeric IDs.

Token cache: `~/.local/state/discord-cli/token.json` (fcntl-locked, multi-process safe).

When reporting results, include the output path, message count, UTC window,
local-time window, filters, and any partial-coverage or REST-error caveats.
`fetch` is oldest-to-newest; `search` is newest-to-oldest.

Bot posts can be embed-only. If `content` is empty, inspect
`embeds[].description` before concluding there was no message.

Full docs: `SKILL.md`. Config schema: `channels.example.yaml`.
