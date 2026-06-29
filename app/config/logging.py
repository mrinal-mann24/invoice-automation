import sys
from loguru import logger
from app.config.settings import get_settings


def configure_logging() -> None:
    settings = get_settings()
    settings.logs_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>",
        colorize=True,
    )
    logger.add(
        settings.logs_dir / "app.log",
        level=settings.log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} — {message}",
        rotation="1 day",
        retention="30 days",
        compression="zip",
        enqueue=True,
    )
