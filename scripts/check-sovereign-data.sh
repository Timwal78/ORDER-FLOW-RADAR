#!/usr/bin/env bash
# SOVEREIGN DATA ENFORCEMENT - ScriptMasterLabs
set -euo pipefail
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
VIOLATIONS=0
SCAN_DIRS=("src")
EXTENSIONS=("ts" "js" "mjs" "cjs")
FILES=()
for dir in "${SCAN_DIRS[@]}"; do
  [[ -d "$dir" ]] || continue
  for ext in "${EXTENSIONS[@]}"; do
    while IFS= read -r f; do FILES+=("$f"); done < <(find "$dir" -name "*.${ext}" 2>/dev/null)
  done
done
if [[ ${#FILES[@]} -eq 0 ]]; then echo "No source files found - skipping."; exit 0; fi
PATTERNS=("confidence:[[:space:]]*0\.[0-9]{2,}" "squeeze:[[:space:]]*(true|false),[[:space:]]" "entry:[[:space:]]*[0-9]+\.[0-9]+,[[:space:]]*target[12]:" "(\/\/|#)[[:space:]]*(mock|fake|demo|placeholder|simul|hardcoded|synthetic|dummy|stub)[[:space:]]" "riskReward:[[:space:]]*[0-9]+\.[0-9]" "['\"][[:space:]]*(mock|fake|demo|placeholder|simulation|synthetic|dummy)[[:space:]]*['\"]"
)
for file in "${FILES[@]}"; do
  for pattern in "${PATTERNS[@]}"; do
    matches=$(grep -nE "$pattern" "$file" 2>/dev/null || true)
    if [[ -n "$matches" ]]; then
      echo -e "${RED}VIOLATION${NC} in ${YELLOW}${file}${NC}:"
      while IFS= read -r line; do echo "  $line"; done <<< "$matches"
      VIOLATIONS=$((VIOLATIONS + 1))
    fi
  done
done
if [[ $VIOLATIONS -gt 0 ]]; then echo -e "${RED}BLOCKED: ${VIOLATIONS} violation(s).${NC}"; exit 1; else echo "PASS"; exit 0; fi
