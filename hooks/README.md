# Git hooks (tracked, portable)

`.git/hooks/` is not tracked by git, so hooks don't survive a clone on their own. This repo keeps
its hooks here in a tracked `hooks/` directory and points git at it with `core.hooksPath`.

## Install (one line, once per clone)

```sh
git config core.hooksPath hooks
```

That tells git to run hooks from `hooks/` instead of `.git/hooks/`. Because `hooks/` is committed,
the scripts come with every clone — you only re-run the one command after a fresh clone.

To confirm it's active:

```sh
git config core.hooksPath      # should print: hooks
```

To disable:

```sh
git config --unset core.hooksPath
```

## Hooks

- **`pre-commit`** — blocks direct commits to `main`. The live site deploys from `main`, so `main`
  only moves via an explicit `git merge dev` when a build-out is validated. Commits on `dev` (or any
  other branch) are unaffected. A genuinely intentional `main` commit can bypass with
  `git commit --no-verify`.
