import logging
import sys

def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
