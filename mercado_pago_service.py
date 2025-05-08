import logging
import requests
import json
import base64
from datetime import datetime

from config import BOT_CONFIG_FILE, PAYMENTS_FILE
from db_utils import read_json_file, write_json_file
from payment_service import get_payment, update_payment, assign_login_to_user

# Configuração de logging
logger = logging.getLogger(__name__)

def get_mercado_pago_settings():
    """
    Obtém as configurações do Mercado Pago.
    
    Returns:
        dict: Configurações do Mercado Pago
    """
    bot_config = read_json_file(BOT_CONFIG_FILE)
    payment_settings = bot_config.get('payment_settings', {})
    return payment_settings.get('mercado_pago', {})


def create_pix_payment(payment_id, amount, payer_name, plan_type):
    """
    Cria um pagamento PIX usando a API do Mercado Pago.
    
    Args:
        payment_id (str): ID do pagamento interno
        amount (float): Valor do pagamento
        payer_name (str): Nome do pagante
        plan_type (str): Tipo de plano
    
    Returns:
        tuple: (bool, dict) - Sucesso da operação e dados do pagamento
    """
    try:
        # Obter configurações do Mercado Pago
        mp_settings = get_mercado_pago_settings()
        
        if not mp_settings.get('enabled', False):
            logger.error("Mercado Pago não está habilitado nas configurações")
            return False, {"error": "Mercado Pago não está habilitado"}
        
        access_token = mp_settings.get('access_token')
        
        if not access_token:
            logger.error("Token de acesso do Mercado Pago não configurado")
            return False, {"error": "Token de acesso não configurado"}
        
        # Preparar dados para a API
        url = "https://api.mercadopago.com/v1/payments"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        # Descrição do pagamento
        description = f"Plano {plan_type} - Pagamento #{payment_id[:8]}"
        
        # Payload JSON para criar o pagamento
        payload = {
            "transaction_amount": float(amount),
            "description": description,
            "payment_method_id": "pix",
            "payer": {
                "email": f"cliente_{payment_id[:8]}@email.com",  # Email fictício
                "first_name": payer_name
            }
        }
        
        # Fazer requisição para criar o pagamento
        response = requests.post(url, json=payload, headers=headers)
        
        # Verificar resposta
        if response.status_code == 201:
            payment_data = response.json()
            
            # Extrair dados importantes
            mp_payment_id = payment_data.get('id')
            pix_code = payment_data.get('point_of_interaction', {}).get('transaction_data', {}).get('qr_code')
            pix_image = payment_data.get('point_of_interaction', {}).get('transaction_data', {}).get('qr_code_base64')
            
            # Registrar dados na base interna
            payment_update = {
                'mp_payment_id': mp_payment_id,
                'pix_code': pix_code,
                'pix_image': pix_image,
                'payment_method': 'pix_mercado_pago'
            }
            
            update_payment(payment_id, payment_update)
            
            return True, {
                'mp_payment_id': mp_payment_id,
                'pix_code': pix_code,
                'pix_image': pix_image
            }
        else:
            logger.error(f"Erro ao criar pagamento PIX no Mercado Pago: {response.text}")
            return False, {"error": f"Erro {response.status_code}: {response.text}"}
    
    except Exception as e:
        logger.error(f"Exceção ao criar pagamento PIX: {str(e)}")
        return False, {"error": str(e)}


def check_payment_status(mp_payment_id):
    """
    Verifica o status de um pagamento no Mercado Pago.
    
    Args:
        mp_payment_id (str): ID do pagamento no Mercado Pago
    
    Returns:
        tuple: (bool, str) - Sucesso da operação e status do pagamento
    """
    try:
        # Obter configurações do Mercado Pago
        mp_settings = get_mercado_pago_settings()
        access_token = mp_settings.get('access_token')
        
        if not access_token:
            logger.error("Token de acesso do Mercado Pago não configurado")
            return False, "not_configured"
        
        # Preparar requisição
        url = f"https://api.mercadopago.com/v1/payments/{mp_payment_id}"
        
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        # Fazer requisição para verificar o status
        response = requests.get(url, headers=headers)
        
        # Verificar resposta
        if response.status_code == 200:
            payment_data = response.json()
            status = payment_data.get('status', 'unknown')
            
            # Mapear status do Mercado Pago para status interno
            if status == 'approved':
                return True, 'completed'
            elif status == 'pending':
                return True, 'pending'
            elif status in ['rejected', 'cancelled', 'refunded', 'charged_back']:
                return True, 'rejected'
            else:
                return True, 'pending'  # Status desconhecido, manter como pendente
        else:
            logger.error(f"Erro ao verificar status do pagamento: {response.text}")
            return False, "error"
    
    except Exception as e:
        logger.error(f"Exceção ao verificar status do pagamento: {str(e)}")
        return False, "error"


def cancel_payment_in_mercado_pago(mp_payment_id):
    """
    Cancela um pagamento no Mercado Pago.
    
    Args:
        mp_payment_id (str): ID do pagamento no Mercado Pago
    
    Returns:
        bool: True se o cancelamento foi bem-sucedido, False caso contrário
    """
    try:
        # Obter configurações do Mercado Pago
        mp_settings = get_mercado_pago_settings()
        access_token = mp_settings.get('access_token')
        
        if not access_token:
            logger.error("Token de acesso do Mercado Pago não configurado")
            return False
        
        # Preparar requisição
        url = f"https://api.mercadopago.com/v1/payments/{mp_payment_id}"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "status": "cancelled"
        }
        
        # Fazer requisição para cancelar o pagamento
        response = requests.put(url, json=payload, headers=headers)
        
        # Verificar resposta
        if response.status_code == 200:
            logger.info(f"Pagamento {mp_payment_id} cancelado no Mercado Pago com sucesso")
            return True
        else:
            logger.error(f"Erro ao cancelar pagamento {mp_payment_id} no Mercado Pago: {response.text}")
            return False
    
    except Exception as e:
        logger.error(f"Exceção ao cancelar pagamento no Mercado Pago: {str(e)}")
        return False


def process_mercado_pago_webhook(data):
    """
    Processa um webhook do Mercado Pago.
    
    Args:
        data (dict): Dados recebidos no webhook
    
    Returns:
        tuple: (bool, str) - Sucesso da operação e mensagem
    """
    try:
        # Verificar tipo de notificação
        if data.get('type') != 'payment':
            logger.info(f"Webhook ignorado, tipo não suportado: {data.get('type')}")
            return False, "Tipo de notificação não suportado"
        
        # Obter ID do pagamento
        mp_payment_id = data.get('data', {}).get('id')
        
        if not mp_payment_id:
            logger.error("ID do pagamento não encontrado no webhook")
            return False, "ID do pagamento não encontrado"
        
        # Verificar status do pagamento
        success, status = check_payment_status(mp_payment_id)
        
        if not success:
            logger.error(f"Erro ao verificar status do pagamento {mp_payment_id}")
            return False, "Erro ao verificar status do pagamento"
        
        # Encontrar pagamento interno correspondente
        payments = read_json_file(PAYMENTS_FILE)
        internal_payment_id = None
        
        for payment_id, payment in payments.items():
            if payment.get('mp_payment_id') == str(mp_payment_id):
                internal_payment_id = payment_id
                break
        
        if not internal_payment_id:
            logger.error(f"Pagamento interno não encontrado para MP payment {mp_payment_id}")
            return False, "Pagamento interno não encontrado"
        
        # Obter dados do pagamento interno
        payment = get_payment(internal_payment_id)
        
        if not payment:
            logger.error(f"Erro ao obter dados do pagamento {internal_payment_id}")
            return False, "Erro ao obter dados do pagamento"
        
        # Atualizar status do pagamento
        if status == 'completed' and payment['status'] != 'completed':
            # Pagamento aprovado
            if assign_login_to_user(payment['user_id'], payment['plan_type'], internal_payment_id):
                update_payment(internal_payment_id, {'status': 'completed'})
                return True, "Pagamento aprovado e login atribuído"
            else:
                update_payment(internal_payment_id, {'status': 'waiting_login'})
                return True, "Pagamento aprovado, aguardando login"
        elif status == 'rejected' and payment['status'] != 'rejected':
            # Pagamento rejeitado
            update_payment(internal_payment_id, {'status': 'rejected'})
            return True, "Pagamento rejeitado"
        else:
            # Outro status
            return True, f"Status atualizado: {status}"
    
    except Exception as e:
        logger.error(f"Exceção ao processar webhook do Mercado Pago: {str(e)}")
        return False, str(e)