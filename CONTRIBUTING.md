# Contributing to Legalize

## The #1 contribution: add your country

Writing a fetcher for your country's legislation is the highest-impact contribution. See **[ADDING_A_COUNTRY.md](ADDING_A_COUNTRY.md)** for the full technical guide.

## Development setup

```bash
git clone https://github.com/legalize-dev/legalize-pipeline.git
cd legalize-pipeline
pip install -e ".[dev]"
pytest tests/ -v        # 459 tests
ruff check src/ tests/  # lint
```

## Code conventions

- Python 3.12+, type hints encouraged
- English for all code, comments, and variable names
- `ruff` for linting, `pytest` for tests
- Git operations via `subprocess` (not GitPython) for full control over `GIT_AUTHOR_DATE`

## Pull request process

1. Fork and create a branch (`git checkout -b add-country-de`)
2. Run `pytest tests/ -v && ruff check src/ tests/`
3. Submit a PR describing the data source and how the fetcher works

For new country PRs, include:
- Sample fixture data (a few XML/JSON files from the source)
- Tests that parse the fixtures
- A note on the data source's license/terms of use

## Becoming a maintainer

If you want to look after the country you're shipping (not just hand it
off), say so in the PR body. See [MAINTAINERS.md](MAINTAINERS.md) for the
federated model, the scope of country ownership, and the ground rules.

## Questions?

Open an issue or start a discussion.
