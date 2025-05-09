"""
Script para testar os handlers do Vercel localmente.
Isso permite verificar se os endpoints funcionam antes de fazer o deploy.
"""
import os
import json
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vercel_test")

# Porta para o servidor de teste
PORT = 8080

def print_divider():
    print("\n" + "=" * 70)

class MockRequest:
    """Mock para simular as requisições para os handlers do Vercel"""
    def __init__(self, path="/", method="GET"):
        self.path = path
        self.method = method
        self.url = f"http://localhost:{PORT}{path}"
        self.headers = {}
        self.query = {}
        self.cookies = {}
        
    def __repr__(self):
        return f"MockRequest(path='{self.path}', method='{self.method}')"

class MockResponse:
    """Mock para capturar as respostas dos handlers do Vercel"""
    def __init__(self):
        self.status = 200
        self.headers = {}
        self.body = ""
        
    def __repr__(self):
        return f"MockResponse(status={self.status}, body_len={len(self.body) if isinstance(self.body, str) else 'binary'})"

def test_handler(handler_path, request_path="/"):
    """Testa um handler do Vercel"""
    print_divider()
    print(f"Testando handler: {handler_path}")
    print(f"Path da requisição: {request_path}")
    
    try:
        # Configurar variáveis de ambiente para simular o Vercel
        os.environ["VERCEL"] = "1"
        os.environ["VERCEL_ENV"] = "development"
        
        # Importar o handler dinamicamente
        sys.path.insert(0, os.path.dirname(handler_path))
        module_name = os.path.basename(handler_path).replace(".py", "")
        
        print(f"Importando módulo: {module_name} de {os.path.dirname(handler_path)}")
        
        # Criar mock das requisições/respostas
        req = MockRequest(path=request_path)
        res = MockResponse()
        
        # Tentar importar e executar o handler
        try:
            module = __import__(module_name)
            if hasattr(module, "handler"):
                print("Executando o handler...")
                result = module.handler(req, res)
                
                # Formatar resultado
                if isinstance(result, dict):
                    print(f"Status: {result.get('statusCode', 'N/A')}")
                    print(f"Corpo da resposta:")
                    try:
                        body = result.get('body', '')
                        if isinstance(body, str) and body.startswith('{'):
                            print(json.dumps(json.loads(body), indent=2))
                        else:
                            print(body)
                    except:
                        print(result.get('body', 'N/A'))
                else:
                    print(f"Resposta: {res}")
                    if hasattr(res, 'body') and res.body:
                        print(f"Corpo: {res.body}")
            else:
                # Tentar executar como servidor HTTP
                print("Handler 'handler' não encontrado, tentando iniciar servidor HTTP...")
                start_test_server(handler_path)
                
        except Exception as e:
            print(f"Erro ao executar o handler: {e}")
            import traceback
            traceback.print_exc()
    
    except Exception as e:
        print(f"Erro geral ao testar handler: {e}")
    
    finally:
        # Limpar path para próximos imports
        if os.path.dirname(handler_path) in sys.path:
            sys.path.remove(os.path.dirname(handler_path))

def start_test_server(handler_path):
    """Inicia um servidor HTTP para testar o handler"""
    dir_name = os.path.dirname(handler_path)
    module_name = os.path.basename(handler_path).replace(".py", "")
    
    # Importar o módulo Handler
    try:
        sys.path.insert(0, dir_name)
        mod = __import__(module_name)
        
        if hasattr(mod, "Handler"):
            # Usar o Handler do módulo
            handler_class = mod.Handler
            
            def run_server():
                server = HTTPServer(('localhost', PORT), handler_class)
                print(f"\nServidor rodando em http://localhost:{PORT}")
                print("Pressione Ctrl+C no terminal para parar o servidor...")
                server.serve_forever()
            
            # Iniciar servidor em thread separada
            server_thread = threading.Thread(target=run_server)
            server_thread.daemon = True
            server_thread.start()
            
            # Deixar o servidor rodar por um tempo
            time.sleep(1)
            print(f"\nPara testar, abra o navegador em: http://localhost:{PORT}")
            print("O servidor vai parar automaticamente após 30 segundos...")
            
            try:
                time.sleep(30)
            except KeyboardInterrupt:
                print("\nServidor interrompido pelo usuário.")
            
            return True
        else:
            print(f"Classe 'Handler' não encontrada em {module_name}.")
            return False
    
    except Exception as e:
        print(f"Erro ao iniciar servidor de teste: {e}")
        return False
    
    finally:
        if dir_name in sys.path:
            sys.path.remove(dir_name)

if __name__ == "__main__":
    print("\nTestando handlers do Vercel localmente")
    print("=====================================\n")
    
    # Testar os diferentes handlers
    test_handler("api/serverless.py", "/api/health")
    test_handler("api/serverless.py", "/api/status")
    
    # Verificar se os arquivos wsgi.py e vercel.py contêm handlers
    # adequados que podem ser testados diretamente
    test_handler("api/wsgi.py", "/")
    test_handler("api/vercel.py", "/")
    
    print_divider()
    print("Testes concluídos!")
    print_divider()