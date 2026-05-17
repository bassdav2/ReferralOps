#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

set +e
"$ROOT_DIR/scripts/start_judge_demo.sh"
EXIT_CODE=$?
set -e

if [ "$EXIT_CODE" -ne 0 ]; then
  echo
  echo "ReferralOps launcher failed with exit code $EXIT_CODE."
  if [ -t 0 ]; then
    read -r -p "Press Return to close this window..." _
  fi
fi

exit "$EXIT_CODE"
