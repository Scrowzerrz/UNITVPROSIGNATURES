import os
import threading
import logging
from config import BOT_TOKEN

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Verificar e corrigir pagamentos inconsistentes na inicialização do servidor
def check_and_fix_inconsistent_payments():
    try:
        # Import here to avoid circular imports
        from bot import fix_inconsistent_payments
        
        # Executar a função de correção
        fixed = fix_inconsistent_payments()
        if fixed > 0:
            logger.info(f"[Servidor Web] Corrigidos {fixed} pagamentos inconsistentes na inicialização")
    except Exception as e:
        logger.error(f"Erro ao verificar pagamentos inconsistentes: {e}")

# Start bot in a separate thread if token is configured
def start_bot():
    if BOT_TOKEN:
        try:
            # Import inside function to avoid immediate loading if token is not set
            from bot import run_bot
            logger.info("Starting Telegram bot in background thread...")
            run_bot()
        except Exception as e:
            logger.error(f"Error running bot: {e}")
    else:
        logger.warning("No Telegram bot token provided. Bot will not be started.")

# Import the Flask app
from app import app

# Executar a correção de pagamentos inconsistentes na inicialização
check_and_fix_inconsistent_payments()

# Start bot in a background thread
if BOT_TOKEN:
    logger.info("Initializing Telegram bot thread...")
    bot_thread = threading.Thread(target=start_bot)
    bot_thread.daemon = True
    bot_thread.start()
    logger.info("Telegram bot thread started")
else:
    logger.warning("Telegram bot not started. Set TELEGRAM_BOT_TOKEN environment variable to enable it.")

if __name__ == "__main__":
    # O bot já foi inicializado acima, não precisamos iniciar novamente
    # Start flask app
    port = int(os.environ.get("PORT", 5000))
    from app import app as flask_app
    flask_app.run(host="0.0.0.0", port=port, debug=True)
