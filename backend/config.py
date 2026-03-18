from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    data_dir: Path = Path("./data")
    host: str = "127.0.0.1"
    port: int = 8001
    # Optional absolute path to exiftool executable.
    # Leave empty to rely on PATH. Set in .env as EXIFTOOL_PATH=C:\...\exiftool.exe
    exiftool_path: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
