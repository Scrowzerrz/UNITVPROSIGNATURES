"""
Script para testar o endpoint serverless mais simples localmente
"""
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
import sys
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("serverless_test")

# Porta para o servidor de teste
PORT = 8000

if __name__ == "__main__":
    print("\n==================================================")
    print("Iniciando servidor de teste para endpoint serverless")
    print("==================================================\n")
    
    # Definir variáveis de ambiente para simular o Vercel
    os.environ["VERCEL"] = "1"
    os.environ["VERCEL_ENV"] = "development"
    os.environ["VERCEL_REGION"] = "local"
    
    # Importar o Handler da API serverless
    api_path = "api"
    if api_path not in sys.path:
        sys.path.insert(0, api_path)
    
    # Tentar importar o módulo serverless
    try:
        from serverless import Handler
        
        print(f"Iniciando servidor na porta {PORT}...")
        server = HTTPServer(('0.0.0.0', PORT), Handler)
        
        print(f"\nServidor rodando em http://0.0.0.0:{PORT}")
        print("URLs para testar:")
        print(f" - http://localhost:{PORT}/api/health")
        print(f" - http://localhost:{PORT}/api/status")
        print("\nPressione Ctrl+C para encerrar")
        
        # Iniciar o servidor
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor encerrado pelo usuário")
        
    except ImportError as e:
        print(f"Erro ao importar módulo serverless: {e}")
    except Exception as e:
        print(f"Erro ao iniciar servidor: {e}")