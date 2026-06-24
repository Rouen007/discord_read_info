# Discord Skill

Minimal Discord read CLI. See `SKILL.md` for the full reference and
`channels.example.yaml` for the config schema.

## TL;DR

```bash
discord fetch    <channel>  [--days N | --hours N] [--author NAME] [--out PATH]
discord search   <guild>    "QUERY" [--channel CH] [--author-id ID] [--days N]
discord channels                       # show what aliases are configured
discord status                         # is CDP endpoint reachable?
discord setup                          # launch Chrome with CDP and open discord.com
```

`<channel>` / `<guild>` accept a numeric Discord ID or an alias from
`~/.config/discord-cli/channels.yaml` (case-insensitive). Use `discord channels`
to see what's currently configured.

## Output schema

```jsonc
{ "id", "channel_id", "timestamp", "author": { "id", "username", "global_name" },
  "content", "attachments"?, "referenced_message"? }
```

`timestamp` is UTC ISO 8601 — always convert to whatever local zone the user
expects before showing.

## Persistence

| Path | Purpose |
|---|---|
| `~/.config/discord-cli/channels.yaml` | private channel/guild/author aliases |
| `~/.local/state/discord-cli/token.json` | cached auth token (mode 600, fcntl-locked) |
| `~/.local/state/discord-cli/chrome-profile/` | Chrome user-data-dir created by `discord setup` |

None of these live inside the skill directory, so the skill itself can be
shared/uploaded freely.
