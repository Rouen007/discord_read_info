# Discord Skill (for sibling agents)

Minimal `discord` CLI — read Discord messages via REST API.

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

Full docs: `SKILL.md`. Config schema: `channels.example.yaml`.
