import os
from pathlib import Path
from dotenv import load_dotenv

# load .env located next to this file
load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
