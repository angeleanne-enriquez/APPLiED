import os
from pathlib import Path
from dotenv import load_dotenv

# load .env located next to this file
load_dotenv(dotenv_path=Path(__file__).with_name('.env'))

DATABASE_URL = os.getenv('DATABASE_URL')
