from flask import Flask
import sys
import os
import logging

# Configurar logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("vercel_handler")

# Adicionar o diretório raiz ao path para importação
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    # Importar o app Flask
    from app import app as flask_app
    
    # Configurações específicas para o Vercel
    if 'VERCEL' in os.environ:
        # Desativar threads do bot para o ambiente serverless
        flask_app.config['DISABLE_BOT_THREADS'] = True
        logger.info("Vercel environment detected, bot threads disabled")
    
    # Handler para o Vercel
    def handler(request, response):
        logger.info(f"Handling request to: {request.url}")
        return flask_app(request, response)
        
except Exception as e:
    logger.error(f"Error loading Flask app: {e}")
    
    def handler(request, response):
        response.status = 500
        response.body = f"Server initialization error: {str(e)}"
        return response