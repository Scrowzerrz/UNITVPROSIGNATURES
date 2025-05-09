"""
Webhook do Telegram para o ambiente serverless Vercel.
Este endpoint recebe e processa atualizações enviadas pelo Telegram.
"""
import os
import sys
import json
import logging
from typing import Dict, Any, Optional

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Adicionar diretório raiz ao path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def handler(req, context):
    """
    Handler para receber updates do Telegram via webhook.
    
    Args:
        req: Requisição HTTP recebida pelo Vercel
        context: Contexto da função serverless
        
    Returns:
        Resposta para o Telegram
    """
    try:
        # Verificar método HTTP
        if req.method != 'POST':
            return {
                'statusCode': 405,
                'body': json.dumps({'error': 'Método não permitido'})
            }
        
        # Verificar token de segurança (definido nas variáveis de ambiente do Vercel)
        webhook_token = os.environ.get('WEBHOOK_TOKEN')
        if webhook_token:
            req_token = req.query.get('token')
            if not req_token or req_token != webhook_token:
                logger.warning(f"Token inválido. Esperado: {webhook_token}, Recebido: {req_token}")
                return {
                    'statusCode': 401,
                    'body': json.dumps({'error': 'Token de webhook inválido'})
                }
        
        # Obter corpo da requisição como objeto de update do Telegram
        update = None
        try:
            # Se for string, converter para JSON
            if isinstance(req.body, str):
                update = json.loads(req.body)
            else:
                # Se já for objeto (dict), usar diretamente
                update = req.body
        except Exception as e:
            logger.error(f"Erro ao processar corpo da requisição: {e}")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Corpo da requisição inválido'})
            }
        
        # Importar função de processamento do bot
        try:
            from bot import process_telegram_update
            result = process_telegram_update(update)
            return {
                'statusCode': 200,
                'body': json.dumps(result)
            }
        except Exception as e:
            logger.error(f"Erro ao processar update do Telegram: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': 'Erro interno no processamento do update',
                    'message': str(e)
                })
            }
    
    except Exception as e:
        logger.error(f"Erro não tratado no webhook: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Erro interno no servidor',
                'message': str(e)
            })
        }