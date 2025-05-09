from http.server import BaseHTTPRequestHandler
import os
import sys
import traceback
import json
import logging

# Configurar logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("vercel_api")

# Adicionar diretório raiz ao path para importações
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# Variável para a app Flask
flask_app = None

# Inicializar a aplicação
try:
    # Marcador para ambiente Vercel
    if 'VERCEL_ENV' not in os.environ:
        os.environ['VERCEL'] = '1'
    
    # Importar a aplicação Flask
    from app import app
    flask_app = app
    
    # Registrar sucesso
    logger.info("Flask app successfully loaded")
    
except Exception as e:
    error_msg = traceback.format_exc()
    logger.error(f"Failed to load Flask app: {error_msg}")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request()
    
    def do_POST(self):
        self.handle_request()
    
    def handle_request(self):
        try:
            if flask_app:
                # Simulação básica de WSGI para o Flask
                env = {
                    'REQUEST_METHOD': self.command,
                    'PATH_INFO': self.path,
                    'QUERY_STRING': '',
                    'SERVER_NAME': self.server.server_name,
                    'SERVER_PORT': str(self.server.server_port),
                    'wsgi.input': self.rfile,
                    'wsgi.errors': sys.stderr,
                    'wsgi.multithread': False,
                    'wsgi.multiprocess': False,
                    'wsgi.run_once': False,
                    'wsgi.version': (1, 0),
                    'wsgi.url_scheme': 'https'
                }
                
                # Resposta simplificada
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                
                # Mensagem de sucesso
                response = "Aplicativo Flask carregado com sucesso no Vercel!"
                self.wfile.write(response.encode())
                
            else:
                # Erro caso o Flask não tenha carregado
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                
                error_response = {
                    "error": "Failed to initialize Flask application",
                    "message": "Check Vercel logs for details"
                }
                self.wfile.write(json.dumps(error_response).encode())
                
        except Exception as e:
            # Tratamento de erros gerais
            logger.error(f"Error handling request: {traceback.format_exc()}")
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            error_response = {
                "error": "Internal server error",
                "message": str(e)
            }
            self.wfile.write(json.dumps(error_response).encode())

def app(req):
    """
    Função de ponto de entrada para o Vercel
    """
    try:
        logger.info(f"Received request: {req.url}")
        
        # Se o app Flask estiver disponível, tente usá-lo diretamente
        if flask_app:
            # Tenta usar a app diretamente (modo básico para depuração)
            return {
                "statusCode": 200,
                "body": "Flask app loaded successfully"
            }
        else:
            # Retorna erro se o Flask não foi carregado
            error_msg = "Flask application could not be initialized"
            logger.error(error_msg)
            
            return {
                "statusCode": 500,
                "body": error_msg
            }
            
    except Exception as e:
        logger.error(f"Error in handler: {traceback.format_exc()}")
        return {
            "statusCode": 500,
            "body": f"Error: {str(e)}"
        }