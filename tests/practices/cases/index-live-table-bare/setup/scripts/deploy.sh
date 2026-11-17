#!/usr/bin/env bash
# Usage: scripts/deploy.sh <the commit deployed last>
set -euo pipefail

for file in $(git diff --name-only --diff-filter=A "$1" HEAD -- supabase/migrations | sort); do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$file"
done

kubectl rollout restart deployment/ledgerly
