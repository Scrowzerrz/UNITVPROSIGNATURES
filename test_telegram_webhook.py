"""
Este script envia uma requisição de teste para o endpoint do webhook do Telegram.
Ele simula o comportamento do Telegram enviando uma atualização para o endpoint.
"""
import json
import requests
import argparse
import os

def test_webhook(url, token=None, command='/start', user_id=12345678):
    """
    Envia uma requisição de teste para o webhook simulando uma mensagem do Telegram.
    
    Args:
        url (str): URL completa do endpoint de webhook
        token (str, optional): Token de webhook para autenticação (se necessário)
        command (str, optional): Comando a ser simulado (/start por padrão)
        user_id (int, optional): ID de usuário Telegram simulado
    """
    # Construir URL com token se fornecido
    if token:
        if '?' in url:
            url = f"{url}&token={token}"
        else:
            url = f"{url}?token={token}"
    
    # Simular payload de update do Telegram para o comando /start
    payload = {
        "update_id": 123456789,
        "message": {
            "message_id": 1,
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": "Test",
                "username": "testuser",
                "language_code": "pt-br"
            },
            "chat": {
                "id": user_id,
                "first_name": "Test",
                "username": "testuser",
                "type": "private"
            },
            "date": 1619712345,
            "text": command
        }
    }
    
    print(f"Enviando requisição para: {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    # Enviar a requisição POST
    try:
        response = requests.post(
            url, 
            json=payload,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'TelegramBot-WebhookTest/1.0'
            }
        )
        
        # Exibir resposta
        print(f"\nStatus: {response.status_code}")
        print(f"Resposta: {response.text}")
        
        # Tentar formatar como JSON se possível
        try:
            json_response = response.json()
            print(f"\nResposta formatada:\n{json.dumps(json_response, indent=2)}")
        except:
            pass
            
        return response.status_code == 200
        
    except Exception as e:
        print(f"Erro ao enviar requisição: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Teste de webhook do Telegram")
    parser.add_argument("--url", required=True, help="URL do webhook (ex: https://seu-app.vercel.app/api/telegram-webhook)")
    parser.add_argument("--token", help="Token de webhook para autenticação")
    parser.add_argument("--command", default="/start", help="Comando a ser simulado (/start por padrão)")
    parser.add_argument("--user-id", type=int, default=12345678, help="ID de usuário Telegram simulado")
    
    args = parser.parse_args()
    
    # Se o token não for fornecido, tentar obter do ambiente
    token = args.token
    if not token and 'WEBHOOK_TOKEN' in os.environ:
        token = os.environ['WEBHOOK_TOKEN']
        print(f"Usando token de webhook do ambiente: {token}")
    
    test_webhook(args.url, token, args.command, args.user_id)