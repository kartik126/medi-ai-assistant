import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import get_settings
from backend.db import migrate

if __name__ == "__main__":
    migrate(get_settings().database_url)
    print("Database migrations applied.")
