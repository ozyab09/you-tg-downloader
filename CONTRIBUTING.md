# Contributing

## Правила

- **Прямые пуши в `main` запрещены.** Все изменения — через Pull Request.
- PR требует зелёного CI: `ruff check` + `pytest` (Python 3.12) + сборка Docker-образа.
- Минимум один approve на ревью.

## Workflow

```bash
# 1. Ветка от main
git checkout main && git pull
git checkout -b feat/my-feature

# 2. Изменения + локальная проверка (то же, что гоняет CI)
pytest
ruff check app tests

# 3. Коммит и пуш ветки
git add -A && git commit -m "feat: ..."
git push -u origin feat/my-feature

# 4. Pull Request в main
gh pr create --fill
```

## Коммиты

Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.

## Тесты

Новая функциональность — с тестами. Тесты не должны требовать сеть,
токенов и реального Telegram.
