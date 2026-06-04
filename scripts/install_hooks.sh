#!/usr/bin/env bash
# Install the pre-commit hook that regenerates ARCHITECTURE.md.
set -e

HOOKS_DIR="$(git rev-parse --git-dir)/hooks"
HOOK_FILE="$HOOKS_DIR/pre-commit"

cat > "$HOOK_FILE" << 'EOF'
#!/usr/bin/env bash
# PayGuard pre-commit hook: regenerate ARCHITECTURE.md and re-stage it.
set -e

echo "[hook] Regenerating ARCHITECTURE.md…"
python scripts/gen_architecture.py
git add ARCHITECTURE.md
echo "[hook] ARCHITECTURE.md updated and staged ✓"
EOF

chmod +x "$HOOK_FILE"
echo "Pre-commit hook installed at $HOOK_FILE"
