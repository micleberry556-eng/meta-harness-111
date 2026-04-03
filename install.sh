#!/usr/bin/env bash
# Meta-Harness Training Interface — Auto-Installer
# Works on Linux and macOS. Installs Ollama, Python dependencies, and sets up the service.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
DATA_DIR="$SCRIPT_DIR/data"
PYTHON_MIN_VERSION="3.10"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# --- Check Python version ---
check_python() {
    local py=""
    for candidate in python3 python; do
        if command -v "$candidate" &>/dev/null; then
            local ver
            ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
            if [ -n "$ver" ]; then
                local major minor
                major=$(echo "$ver" | cut -d. -f1)
                minor=$(echo "$ver" | cut -d. -f2)
                if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
                    py="$candidate"
                    break
                fi
            fi
        fi
    done
    if [ -z "$py" ]; then
        error "Python >= $PYTHON_MIN_VERSION is required but not found."
        error "Install Python 3.10+ and re-run this script."
        exit 1
    fi
    echo "$py"
}

# --- Install Ollama ---
install_ollama() {
    if command -v ollama &>/dev/null; then
        info "Ollama is already installed: $(ollama --version 2>/dev/null || echo 'unknown version')"
        return 0
    fi

    info "Installing Ollama..."
    if [[ "$(uname -s)" == "Linux" ]]; then
        curl -fsSL https://ollama.com/install.sh | sh
    elif [[ "$(uname -s)" == "Darwin" ]]; then
        if command -v brew &>/dev/null; then
            brew install ollama
        else
            error "On macOS, install Ollama manually from https://ollama.com/download or install Homebrew first."
            exit 1
        fi
    else
        error "Unsupported OS: $(uname -s). Install Ollama manually from https://ollama.com/download"
        exit 1
    fi

    if command -v ollama &>/dev/null; then
        info "Ollama installed successfully."
    else
        error "Ollama installation failed. Install manually from https://ollama.com/download"
        exit 1
    fi
}

# --- Setup Python virtual environment ---
setup_venv() {
    local py="$1"
    if [ ! -d "$VENV_DIR" ]; then
        info "Creating Python virtual environment..."
        "$py" -m venv "$VENV_DIR"
    else
        info "Virtual environment already exists."
    fi

    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    info "Installing Python dependencies..."
    pip install --upgrade pip --quiet
    pip install -r "$SCRIPT_DIR/requirements-training.txt" --quiet

    info "Python dependencies installed."
}

# --- Create data directories ---
setup_data() {
    mkdir -p "$DATA_DIR/sessions"
    mkdir -p "$DATA_DIR/knowledge_base"
    mkdir -p "$DATA_DIR/exports"
    info "Data directories ready at $DATA_DIR"
}

# --- Main ---
main() {
    echo ""
    echo "============================================"
    echo "  Meta-Harness Training Interface Installer"
    echo "============================================"
    echo ""

    local py
    py=$(check_python)
    info "Using Python: $py ($($py --version 2>&1))"

    install_ollama
    setup_venv "$py"
    setup_data

    echo ""
    info "Installation complete!"
    echo ""
    echo "  To start the training interface:"
    echo ""
    echo "    source $VENV_DIR/bin/activate"
    echo "    python -m training_interface.app"
    echo ""
    echo "  Then open http://localhost:8000 in your browser."
    echo ""
    echo "  Make sure Ollama is running (ollama serve) before starting."
    echo ""
}

main "$@"
