#!/bin/bash
# ═══════════════════════════════════════════════════════════
# YouTube Channel Cloner — Setup & Push Script
# Run this after extracting the tar.gz
# ═══════════════════════════════════════════════════════════

set -e

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  YouTube Channel Cloner — Setup"
echo "═══════════════════════════════════════════════════════"
echo ""

# Check if git is available
if ! command -v git &> /dev/null; then
    echo "[ERROR] git not found. Install git first."
    exit 1
fi

# Check if we're in the right directory
if [ ! -f "dashboard.py" ]; then
    echo "[ERROR] Run this from the youtube-cloner directory."
    echo "  cd youtube-cloner && bash setup.sh"
    exit 1
fi

# ── Step 1: Configure .env ──
if [ ! -f ".env" ]; then
    echo "[1/4] Creating .env from .env.example..."
    cp .env.example .env
    echo "  IMPORTANT: Edit .env with your real values before running!"
    echo ""
else
    echo "[1/4] .env already exists, skipping."
fi

# ── Step 2: Set up git remote ──
echo "[2/4] Git remote setup..."
echo ""

if git remote get-url origin &> /dev/null; then
    CURRENT=$(git remote get-url origin)
    echo "  Current remote: $CURRENT"
    read -p "  Change remote? (y/N): " change
    if [ "$change" = "y" ] || [ "$change" = "Y" ]; then
        read -p "  New remote URL (e.g. git@github.com:user/repo.git): " REMOTE_URL
        git remote set-url origin "$REMOTE_URL"
        echo "  Remote updated to: $REMOTE_URL"
    fi
else
    read -p "  Remote URL (e.g. git@github.com:user/repo.git): " REMOTE_URL
    if [ -z "$REMOTE_URL" ]; then
        echo "  Skipping remote setup. Add later with:"
        echo "    git remote add origin <URL>"
        echo ""
    else
        git remote add origin "$REMOTE_URL"
        echo "  Remote added: $REMOTE_URL"
    fi
fi

# ── Step 3: Push ──
echo ""
echo "[3/4] Push to remote..."

if git remote get-url origin &> /dev/null; then
    read -p "  Push to origin/main now? (Y/n): " push
    if [ "$push" != "n" ] && [ "$push" != "N" ]; then
        echo "  Pushing..."
        git push -u origin main --force
        echo "  Done! Check your repository."
    else
        echo "  Skipped. Push manually with:"
        echo "    git push -u origin main"
    fi
else
    echo "  No remote configured. Push manually after adding one:"
    echo "    git remote add origin <URL>"
    echo "    git push -u origin main"
fi

# ── Step 4: Verify ──
echo ""
echo "[4/4] Verification..."
echo "  Commit: $(git log --oneline -1)"
echo "  Files: $(git ls-files | wc -l)"
echo "  Branch: $(git branch --show-current)"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "    1. Edit .env with your real values"
echo "    2. pip install -r requirements.txt"
echo "    3. python test_app.py"
echo "    4. python dashboard.py"
echo "═══════════════════════════════════════════════════════"
echo ""
