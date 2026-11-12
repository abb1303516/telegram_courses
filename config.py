import os
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    PROXY = os.getenv("PROXY", "")  # e.g. http://host:port or socks5://user:pass@host:port
    # Separate connections per large file; 1 = single stream (Telethon's own path)
    DOWNLOAD_CONNECTIONS = int(os.getenv("DOWNLOAD_CONNECTIONS", "4"))
    # Opening connections takes ~1.5 s each; smaller files are faster single-stream
    PARALLEL_MIN_MB = int(os.getenv("PARALLEL_MIN_MB", "60"))
    # Enable only after HTTPS is working. Secure cookies are not sent over HTTP.
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE")
    # Trust exactly one local reverse proxy (nginx) when TLS terminates there.
    BEHIND_PROXY = _env_bool("BEHIND_PROXY")
    TRUSTED_HOSTS = [
        host.strip()
        for host in os.getenv("TRUSTED_HOSTS", "").split(",")
        if host.strip()
    ]

    @classmethod
    def validate_security(cls) -> None:
        """Refuse to start with public example credentials."""
        errors = []
        if cls.SECRET_KEY in {
            "",
            "change-me-to-random-string",
            "change-this-to-random-string",
        } or len(cls.SECRET_KEY) < 32:
            errors.append("SECRET_KEY must be a random value of at least 32 characters")
        if cls.APP_PASSWORD in {"", "admin", "mypassword123"} or len(cls.APP_PASSWORD) < 8:
            errors.append("APP_PASSWORD must be non-default and at least 8 characters")
        if errors:
            raise RuntimeError("Unsafe configuration: " + "; ".join(errors))
