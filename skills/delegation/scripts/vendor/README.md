# Vendored code

## parable.py

A stdlib-only bash parser, used by `../subagent-policy` to split a command into the simple commands it
runs. It is vendored verbatim: do not edit it. Replace the file whole and update the pin below.

- Source: https://github.com/ldayton/Parable, `src/parable.py` at commit
  `9f7e15734bd3e5bb9fe252d2491d6f61572f0e57` (the commit ldayton/Dippy pins in its `pyproject.toml`).
- sha256: `34aef27c989befa67daf5b0036ff90432baac350c3d79f7add711d883bca05d1`, checked by
  `tests/delegation/test_vendor.py`.
- License: MIT, see `LICENSE-parable` ("Copyright (c) 2025 Parable authors").
- Needs Python 3.12 or newer.
