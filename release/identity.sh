DEFAULT_GIT_NAME="$(git config user.name 2>/dev/null || true)"
DEFAULT_GIT_EMAIL="$(git config user.email 2>/dev/null || true)"

export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-${DEFAULT_GIT_NAME:-Vehicle Researcher}}"
export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-${DEFAULT_GIT_EMAIL:-user@example.com}}"
export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-${DEFAULT_GIT_NAME:-Vehicle Researcher}}"
export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-${DEFAULT_GIT_EMAIL:-user@example.com}}"
