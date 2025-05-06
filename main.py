import os
import threading
import logging
from app import app
from config import BOT_TOKEN

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Start bot in a separate thread if token is configured
def start_bot():
    if BOT_TOKEN:
        try:
            # Import inside function to avoid immediate loading if token is not set
            from bot import run_bot
            run_bot()
        except Exception as e:
            logger.error(f"Error running bot: {e}")
    else:
        logger.warning("No Telegram bot token provided. Bot will not be started.")

if __name__ == "__main__":
    # Start bot thread only if token is available
    if BOT_TOKEN:
        bot_thread = threading.Thread(target=start_bot)
        bot_thread.daemon = True
        bot_thread.start()
        logger.info("Telegram bot thread started")
    else:
        logger.warning("Telegram bot not started. Set TELEGRAM_BOT_TOKEN environment variable to enable it.")
    
    # Start flask app
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
