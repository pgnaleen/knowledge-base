#!/bin/bash

# Setup script for Property Advisory AI Agent
# Copies all .env.example files to .env (if .env doesn't already exist)

echo "🚀 Setting up Property Advisory AI Agent..."
echo ""

env_examples=(
    "KB-Pipeline/.env.example"
    "sg-property-agent/backend/.env.example"
    "sg-property-agent/frontend/.env.example"
    "sg-property-agent/mcp-server/.env.example"
)

created=0
skipped=0

for example in "${env_examples[@]}"; do
    env_file="${example%.example}"

    if [ -f "$example" ]; then
        if [ -f "$env_file" ]; then
            echo "⏭️  Skipping $env_file (already exists)"
            ((skipped++))
        else
            cp "$example" "$env_file"
            echo "✅ Created $env_file"
            ((created++))
        fi
    else
        echo "⚠️  Not found: $example"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ $created -gt 0 ]; then
    echo "📝 Next steps:"
    echo ""
    echo "1. Edit the following files with your API keys:"
    for example in "${env_examples[@]}"; do
        env_file="${example%.example}"
        if [ ! -f "$env_file" ]; then
            echo "   • $env_file"
        fi
    done
    echo ""
    echo "2. At minimum, set one of these in sg-property-agent/backend/.env:"
    echo "   • OPENROUTER_API_KEY=sk-or-..."
    echo "   • OPENAI_API_KEY=sk-..."
    echo ""
    echo "3. Start services:"
    echo "   docker compose up --build -d"
    echo ""
    echo "4. Access the app:"
    echo "   • Frontend: http://localhost:3000"
    echo "   • Backend API: http://localhost:8001/docs"
else
    echo "✨ All .env files already exist!"
    echo ""
    echo "You can now run:"
    echo "   docker compose up --build -d"
fi

echo ""
echo "For more info, see README.md"
echo ""
