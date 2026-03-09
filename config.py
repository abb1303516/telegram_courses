import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    API_ID = int(os.getenv("API_ID", "0"))
    API_HASH = os.getenv("API_HASH", "")
    PHONE = os.getenv("PHONE", "")
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-to-random-string")
    APP_PASSWORD = os.getenv("APP_PASSWORD", "admin")
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "8080"))
    DOWNLOAD_DIR = os.path.abspath(os.getenv("DOWNLOAD_DIR", "./downloads"))
    DATA_FILE = os.path.abspath(os.getenv("DATA_FILE", "./data.json"))
    URL_PREFIX = os.getenv("URL_PREFIX", "")
