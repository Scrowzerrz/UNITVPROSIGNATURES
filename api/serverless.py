"""
Rota serverless simples para o Vercel, quando você precisa de uma resposta mínima
que funcione independentemente da estrutura principal da aplicação.
"""
from http.server import BaseHTTPRequestHandler
import json
import logging
import os
import sys
import traceback

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("serverless")

# Adicionar root ao path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Resposta básica de diagnóstico
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            # Informações básicas de diagnóstico
            response = {
                "status": "online",
                "message": "UniTV API está funcionando no Vercel",
                "path": self.path,
                "environment": {
                    "python_version": sys.version,
                    "vercel": os.environ.get("VERCEL", "Not detected"),
                    "vercel_region": os.environ.get("VERCEL_REGION", "Unknown")
                }
            }
            
            self.wfile.write(json.dumps(response, indent=2).encode())
            
        except Exception as e:
            # Logar erro
            error_details = traceback.format_exc()
            logger.error(f"Error handling request: {error_details}")
            
            # Retornar erro
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            error_response = {
                "status": "error",
                "message": str(e)
            }
            
            self.wfile.write(json.dumps(error_response).encode())
            
    def do_POST(self):
        self.do_GET()  # Mesma resposta para POST para simplificar

def handler(request):
    """
    Função handler para o Vercel
    """
    try:
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "status": "online",
                "message": "UniTV API está funcionando no Vercel",
                "path": request.path if hasattr(request, "path") else "/",
                "vercel": True
            })
        }
    except Exception as e:
        logger.error(f"Error in handler: {traceback.format_exc()}")
        return {
            "statusCode": 500,
            "body": f"Error: {str(e)}"
        }