import logging
from pathlib import Path


def configure_logging(config: dict) -> logging.Logger:
    settings = config["logging"]
    log_path = Path(settings["file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("lifeos-energy")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(
        getattr(
            logging,
            str(settings.get("level", "INFO")).upper(),
            logging.INFO,
        )
    )

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    logfile = logging.FileHandler(log_path, encoding="utf-8")
    logfile.setFormatter(formatter)

    logger.addHandler(console)
    logger.addHandler(logfile)

    return logger
