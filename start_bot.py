#!/usr/bin/env python3
import logging
from bot import run_bot
from config import BOT_TOKEN

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    if BOT_TOKEN:
        logger.info("Starting Telegram bot...")
        run_bot()
    else:
        logger.error("No Telegram bot token provided. Set TELEGRAM_BOT_TOKEN environment variable.")