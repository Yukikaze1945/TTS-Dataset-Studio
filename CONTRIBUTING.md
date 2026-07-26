# Contributing

Thanks for helping improve TTS Dataset Studio.

## Development setup

Use Windows 10/11 x64, Python 3.12, and `uv`.

```powershell
uv sync --extra dev --frozen
uv run ruff check src tests
uv run pytest
```

Keep media, model weights, `.ttds` projects, logs, and generated build folders outside Git.
Tests that need media should create compact fixtures at runtime in pytest temporary directories.

## Pull requests

- Keep each pull request focused on one user-visible change or fix.
- Add or update tests for changed behavior.
- Preserve non-destructive editing: never overwrite imported media or subtitle files.
- Explain UI changes and include a screenshot when layout or timeline behavior changes.
- Confirm Ruff and the full pytest suite pass before requesting review.

## Bug reports

Include Windows version, app version, reproduction steps, expected behavior, and the relevant
tail of `%LOCALAPPDATA%\OpenAI\TTS Dataset Studio\Logs\studio.log`. Do not attach private media
or model files unless you have permission to share them.
