# Access

Everything this project was given for the event: its hardware, hosts and accounts, listed at kickoff. `/public-ready` walks this list to rotate keys and remove hosts afterwards. Names and places only: no key values and no passwords, since this file may end up public.

An entry ends when `/public-ready` or the user removes it. Nothing here expires by itself.

| What | Why the project needs it | How (test account, spend cap, kill switch, VM) | Exact hosts | Where the key lives | Rotated or removed |
|---|---|---|---|---|---|

Exact hosts go in `.claude/settings.local.json` under `sandbox.network.allowedDomains`, written by the user.
