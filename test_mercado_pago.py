import requests
import json
import uuid
from datetime import datetime, timedelta
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ler configuração do Mercado Pago
try:
    with open('data/bot_config.json', 'r') as f:
        bot_config = json.load(f)
    
    mp_settings = bot_config.get('payment_settings', {}).get('mercado_pago', {})
    access_token = mp_settings.get('access_token')
    
    if not access_token:
        logger.error("Token de acesso do Mercado Pago não encontrado")
        exit(1)
    
    # Informações do pagamento de teste
    payment_data = {
        "transaction_amount": 0.01,  # Valor mínimo para teste
        "description": "Teste de pagamento PIX - UniTV",
        "payment_method_id": "pix",
        "payer": {
            "email": "teste@unitv.com",
            "first_name": "Teste",
            "last_name": "UniTV",
            "identification": {
                "type": "CPF",
                "number": "00000000000"
            }
        },
        # Adicionar data de expiração do PIX (10 minutos) no formato correto yyyy-MM-dd'T'HH:mm:ssz
        "date_of_expiration": (datetime.now() + timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
        "notification_url": "https://unitv-subscription-bot.replit.app/webhooks/mercadopago"
    }
    
    # Configurar headers
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": str(uuid.uuid4())
    }
    
    # Fazer requisição à API do Mercado Pago
    logger.info("Tentando criar pagamento PIX de teste no Mercado Pago...")
    response = requests.post(
        "https://api.mercadopago.com/v1/payments",
        data=json.dumps(payment_data),
        headers=headers
    )
    
    # Analisar resposta
    logger.info(f"Status code: {response.status_code}")
    
    if response.status_code == 201:
        # Pagamento criado com sucesso
        mp_response = response.json()
        logger.info(f"Pagamento criado com sucesso! ID: {mp_response['id']}")
        
        # Obter os dados do PIX
        pix_data = mp_response.get('point_of_interaction', {}).get('transaction_data', {})
        qr_code = pix_data.get('qr_code', 'Não disponível')
        qr_code_url = pix_data.get('qr_code_url', 'Não disponível')
        
        logger.info("QR Code PIX gerado com sucesso!")
        logger.info(f"QR Code URL: {qr_code_url}")
        logger.info(f"QR Code Copia e Cola: {qr_code}")
    else:
        # Erro na criação do pagamento
        try:
            error_response = response.json()
            logger.error(f"Erro na criação do pagamento: {json.dumps(error_response, indent=2)}")
        except:
            logger.error(f"Erro na criação do pagamento: {response.text}")
except Exception as e:
    logger.error(f"Erro durante o teste: {e}")