#!/usr/bin/env bash
# Dependency audit that survives a flaky network.
#
# `pip-audit` exits 1 for a real advisory and for a failed connection to PyPI
# alike. A blocking CI step has to tell those apart: a reset connection is not
# a signal about the change under review. If it cannot, the first team it
# inconveniences marks the job `allow_failure: true`, and from then on the
# audit means nothing.
#
# Real advisory  -> fail immediately, retrying will not change the answer.
# Transport error -> retry with backoff.
set -uo pipefail

# The ignore list is EMPTY, and staying empty is the point. Adding an entry
# means accepting a known vulnerability, which is a decision with a reason —
# so the reason belongs in SECURITY.md next to the identifier. A suppression
# without a written reason is an audit that audits nothing.
IGNORED=()

args=(--skip-editable)
# Expanding an empty array under `set -u` is an "unbound variable" error on
# older bash (macOS ships 3.2), so the length is checked first.
if [ ${#IGNORED[@]} -gt 0 ]; then
  for id in "${IGNORED[@]}"; do
    args+=(--ignore-vuln "$id")
  done
fi

MAX_ATTEMPTS=${AUDIT_MAX_ATTEMPTS:-3}
output=""

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  output="$(uv run pip-audit "${args[@]}" 2>&1)"
  status=$?

  echo "$output"

  if [ "$status" -eq 0 ]; then
    exit 0
  fi

  # A real finding: the answer is the same on every attempt.
  if echo "$output" | grep -qiE 'known vulnerabilit'; then
    echo "::error::Dependency audit found vulnerabilities."
    exit 1
  fi

  echo "Attempt ${attempt}/${MAX_ATTEMPTS} failed for a non-vulnerability reason (likely network)."
  if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
    sleep $((attempt * 10))
  fi
done

echo "::error::Dependency audit could not complete after ${MAX_ATTEMPTS} attempts."
exit 1
