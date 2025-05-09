"""
Arquivo WSGI para uso com o Vercel
"""
import os
import sys
import logging

# Configurar logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("vercel_wsgi")

# Adicionar diretório raiz ao path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)

# Verificar e definir variáveis de ambiente
if 'VERCEL' not in os.environ:
    os.environ['VERCEL'] = '1'
    
try:
    # Importar aplicativo Flask
    from app import app
    
    # Desabilitar threads do bot no ambiente Vercel
    app.config['DISABLE_BOT_THREADS'] = True
    
    # Certificar-se de que a configuração de sessão está segura
    if not app.secret_key or app.secret_key == "unitv_secret_key":
        app.secret_key = os.environ.get("SESSION_SECRET", os.urandom(24).hex())
    
    # Função para o Vercel
    def application(environ, start_response):
        """Função WSGI compatível com o Vercel"""
        return app(environ, start_response)
    
    # Exportação para uso com o Vercel
    app = application
    
    logger.info("WSGI application successfully initialized")
    
except Exception as e:
    logger.error(f"Error initializing WSGI application: {e}")
    
    def application(environ, start_response):
        """Função WSGI de fallback em caso de erro"""
        status = '500 Internal Server Error'
        headers = [('Content-type', 'text/plain; charset=utf-8')]
        start_response(status, headers)
        
        return [f"Error initializing application: {str(e)}".encode()]
    
    # Exportação para uso com o Vercel
    app = application