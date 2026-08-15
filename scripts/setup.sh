#!/bin/bash
# Setup script cho AI20K project

set -e

echo "=== AI20K Project Setup ==="

# Check Python version
python3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'"
echo "Python version OK"

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
VISION_PROFILE="${VISION_PROFILE:-cpu}"
case "$VISION_PROFILE" in
    cpu|intel|cuda) ;;
    *) echo "VISION_PROFILE must be cpu, intel, or cuda" >&2; exit 2 ;;
esac
pip install -r "requirements/vision-${VISION_PROFILE}.txt"

# Create .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env — please edit with your API keys"
fi

# Create data directories
mkdir -p data/chroma

echo "Setup complete! Run: uvicorn src.main:app --reload"
