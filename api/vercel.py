from flask import Flask
import sys
import os

# Adicionar o diretório raiz ao path para importação
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importar o app Flask do arquivo principal
from app import app

# Configurações específicas para o Vercel
if 'VERCEL' in os.environ:
    # Desativar threads do bot para o ambiente serverless
    app.config['DISABLE_BOT_THREADS'] = True

# Handler para o Vercel
def handler(request, response):
    return app(request, response)