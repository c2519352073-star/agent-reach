# Agent Reach Local Checkout

This checkout is the source of truth for the local editable Agent Reach install.

- Check for upstream changes with `agent-reach update-local --check`.
- Apply updates with `agent-reach update-local`.
- Do not run the upstream `docs/update.md` flow, `pip install .../main.zip`, or
  `npm update -g @jackwener/opencli` against this checkout.
- Keep skill edits under `agent_reach/skill/`; sync the installed copy with
  `agent-reach skill --install`.
- Keep user configuration in `~/.agent-reach/` and generated files in
  `E:\agent-reach\技能下载文件` untouched.
