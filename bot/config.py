import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAIN_DIR = os.path.join(REPO_ROOT, "brain")
DOCS_DIR = os.path.join(REPO_ROOT, "docs")

THESES_DIR = os.path.join(BRAIN_DIR, "theses")
CONNECTIONS_DIR = os.path.join(BRAIN_DIR, "connections")
VALIDATIONS_DIR = os.path.join(BRAIN_DIR, "validations")
ASSETS_DIR = os.path.join(BRAIN_DIR, "assets")
