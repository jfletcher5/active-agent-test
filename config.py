import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DATABASE_PATH = 'app.db'
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
    MODEL_NAME = "claude-3-5-haiku-20241022"
    DEFAULT_TEMPERATURE = 0 