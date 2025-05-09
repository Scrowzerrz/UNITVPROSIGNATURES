"""
Configurações específicas para o ambiente Vercel.
Este arquivo contém adaptações necessárias para a aplicação rodar no ambiente serverless.
"""
import os
import json
import logging

logger = logging.getLogger(__name__)

def configure_app_for_vercel(app):
    """
    Configurar o aplicativo Flask para funcionar no ambiente Vercel
    """
    # Verificar se estamos no ambiente Vercel
    if 'VERCEL' not in os.environ:
        return
    
    logger.info("Configurando aplicação para ambiente Vercel...")
    
    # Configurar modo de operação sem threads
    app.config['DISABLE_BOT_THREADS'] = True
    
    # Usar armazenamento alternativo se necessário
    # Por exemplo, configurar para usar REDIS ou outro banco de dados 
    # ao invés de arquivos JSON locais em produção

    # Ajustar configurações de sessão para Vercel
    app.config['PREFERRED_URL_SCHEME'] = 'https'
    app.config['SERVER_NAME'] = os.environ.get('VERCEL_URL')

    logger.info("Aplicação configurada para ambiente Vercel")