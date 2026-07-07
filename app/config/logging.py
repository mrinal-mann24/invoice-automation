import sys
from loguru import logger
from app.config.settings import get_settings


def configure_logging() -> None:
    settings = get_settings()
    settings.logs_dir.mkdir(parents=True, exist_ok=True)

    # On Windows the console is often cp1252, which can't encode the emoji/box
    # characters in our log messages (→, ✅, ─) and raises UnicodeEncodeError
    # inside Loguru's sink. Force the stdout stream to UTF-8 and replace any
    # remaining unencodable chars instead of crashing the log call.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

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
