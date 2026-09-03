# Contributing

Thanks for improving `jina-local`.

## Development

```bash
python -m pip install -e 'mcp-gateway[dev]'
python -m pytest tests/ -q
python -m compileall -q mcp-gateway/src tests
```

Changes should be focused, use the existing project dependencies, and include
tests for behavior changes. Keep the MCP tool signatures and structured return
shapes stable unless the change intentionally updates the public contract.

## Pull Requests

Explain the user-visible behavior, list verification commands, and call out
any Docker, GPU, network, or configuration assumptions. CI must pass before a
pull request is merged. Do not include secrets, personal credentials, or
generated model/cache files.
