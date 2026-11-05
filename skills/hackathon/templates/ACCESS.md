# Access

Everything this project was given for the event: its hardware, hosts and accounts, and every setting changed for the mode, listed at kickoff. `/public-ready` walks this list to rotate keys, remove hosts and undo settings afterwards. Names and places only: no key values and no passwords, since this file may end up public.

An entry ends when `/public-ready` or the user removes it. Nothing here expires by itself.

| What | Why the project needs it | How (test account, spend cap, kill switch, VM) | Exact hosts | Where the key lives | Rotated or removed |
|---|---|---|---|---|---|

A row can be a settings change, not only access: a plugin turned off for this repo (`enabledPlugins` in `.claude/settings.local.json`) gets a row, removed by the user when the mode ends.

Exact hosts go in `.claude/settings.local.json` under `sandbox.network.allowedDomains`, written by the user.
