#!/bin/bash
set -e

echo "🔧 Setting up pre-commit hooks..."

# Check if pre-commit is installed
if ! command -v pre-commit &> /dev/null; then
    echo "📦 Installing pre-commit..."
    if command -v pipx &> /dev/null; then
        pipx install pre-commit
    else
        echo "⚠️  pipx not found, using pip..."
        pip install --user pre-commit
    fi
else
    echo "✅ pre-commit already installed"
fi

# Install hooks
echo "🪝 Installing git hooks..."
pre-commit install --install-hooks
pre-commit install --hook-type pre-push

echo ""
echo "✅ Git hooks setup complete!"
echo ""
echo "📋 What was configured:"
echo "   • Pre-commit: ruff lint + format (runs on 'git commit')"
echo "   • Pre-push: pytest with 90% coverage (runs on 'git push')"
echo ""
echo "💡 Test the hooks manually:"
echo "   pre-commit run --all-files"
echo "   pre-commit run --hook-stage push --all-files"
echo ""
