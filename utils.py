import json
import uuid
import time
import logging
import os
import secrets
import hashlib
from datetime import datetime, timedelta
from config import (
    USERS_FILE, PAYMENTS_FILE, LOGINS_FILE, BOT_CONFIG_FILE, AUTH_FILE, SESSION_FILE,
    PLANS, ADMIN_ID, SESSION_EXPIRY_HOURS
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Utility functions for file operations
def read_json_file(file_path):
    try:
        if not os.path.exists(file_path):
            if file_path == USERS_FILE:
                return {}
            elif file_path == PAYMENTS_FILE:
                return {}
            elif file_path == LOGINS_FILE:
                return {'30_days': [], '6_months': [], '1_year': []}
            elif file_path == BOT_CONFIG_FILE:
                return {'sales_enabled': True, 'warning_sent': False, 'sales_suspended_time': None, 'coupons': {}, 
                        'referral_rewards': {'referrer_discount': 10, 'referred_discount': 5, 'free_month_after_referrals': 3}}
            elif file_path == SESSION_FILE:
                return {}
            elif file_path == AUTH_FILE:
                return {'admin_telegram_ids': [], 'allowed_telegram_ids': [], 'access_codes': {}}
            
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        # Return empty default based on file type
        if file_path == USERS_FILE or file_path == PAYMENTS_FILE:
            return {}
        elif file_path == LOGINS_FILE:
            return {'30_days': [], '6_months': [], '1_year': []}
        elif file_path == BOT_CONFIG_FILE:
            return {'sales_enabled': True, 'warning_sent': False, 'sales_suspended_time': None, 'coupons': {}, 
                    'referral_rewards': {'referrer_discount': 10, 'referred_discount': 5, 'free_month_after_referrals': 3}}
        elif file_path == SESSION_FILE:
            return {}
        elif file_path == AUTH_FILE:
            return {'admin_telegram_ids': [], 'allowed_telegram_ids': [], 'access_codes': {}}
        return {}

def write_json_file(file_path, data):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error writing to file {file_path}: {e}")
        return False

# User management functions
def get_user(user_id):
    users = read_json_file(USERS_FILE)
    return users.get(str(user_id))

def save_user(user_id, user_data):
    users = read_json_file(USERS_FILE)
    users[str(user_id)] = user_data
    write_json_file(USERS_FILE, users)
    
def assign_plan_to_user(user_id, plan_type, duration_days=None):
    """
    Atribui um plano a um usuário manualmente.
    
    Args:
        user_id (str): ID do usuário no Telegram
        plan_type (str): Tipo de plano ('30_days', '6_months', '1_year')
        duration_days (int, optional): Duração personalizada em dias. Se None, usa a duração padrão do plano.
    
    Returns:
        bool: True se o plano foi atribuído com sucesso, False caso contrário
    """
    try:
        user = get_user(user_id)
        if not user:
            return False
        
        # Determinar a duração do plano
        if duration_days is None:
            duration_days = PLANS[plan_type]['duration_days']
        
        # Atualizar os dados do usuário
        user['has_active_plan'] = True
        user['plan_type'] = plan_type
        
        # Calcular a data de expiração
        expiration_date = datetime.now() + timedelta(days=duration_days)
        user['plan_expiration'] = expiration_date.isoformat()
        
        # Resetar a notificação de expiração
        user['expiration_notified'] = False
        
        # Salvar as alterações
        save_user(user_id, user)
        
        return True
    except Exception as e:
        logger.error(f"Error assigning plan to user {user_id}: {e}")
        return False

def remove_plan_from_user(user_id):
    """
    Remove o plano atual de um usuário.
    
    Args:
        user_id (str): ID do usuário no Telegram
    
    Returns:
        bool: True se o plano foi removido com sucesso, False caso contrário
    """
    try:
        user = get_user(user_id)
        if not user:
            return False
        
        # Remover dados do plano
        user['has_active_plan'] = False
        user['plan_type'] = None
        user['plan_expiration'] = None
        user['login_info'] = None
        
        # Salvar as alterações
        save_user(user_id, user)
        
        return True
    except Exception as e:
        logger.error(f"Error removing plan from user {user_id}: {e}")
        return False

def ban_user(user_id, reason=None):
    """
    Bane um usuário, impedindo-o de usar o bot.
    
    Args:
        user_id (str): ID do usuário no Telegram
        reason (str, optional): Motivo do banimento
    
    Returns:
        bool: True se o usuário foi banido com sucesso, False caso contrário
    """
    try:
        user = get_user(user_id)
        if not user:
            return False
        
        # Marcar usuário como banido
        user['is_banned'] = True
        user['ban_reason'] = reason
        user['banned_at'] = datetime.now().isoformat()
        
        # Remover plano atual se existir
        user['has_active_plan'] = False
        user['plan_type'] = None
        user['plan_expiration'] = None
        user['login_info'] = None
        
        # Salvar as alterações
        save_user(user_id, user)
        
        return True
    except Exception as e:
        logger.error(f"Error banning user {user_id}: {e}")
        return False

def unban_user(user_id):
    """
    Remove o banimento de um usuário.
    
    Args:
        user_id (str): ID do usuário no Telegram
    
    Returns:
        bool: True se o usuário foi desbanido com sucesso, False caso contrário
    """
    try:
        user = get_user(user_id)
        if not user:
            return False
        
        # Remover banimento
        user['is_banned'] = False
        user['ban_reason'] = None
        user['unbanned_at'] = datetime.now().isoformat()
        
        # Salvar as alterações
        save_user(user_id, user)
        
        return True
    except Exception as e:
        logger.error(f"Error unbanning user {user_id}: {e}")
        return False
        
def add_seasonal_discount(discount_percent, expiration_days, applicable_plans=None):
    """
    Adiciona um desconto sazonal para todos os usuários.
    
    Args:
        discount_percent (int): Percentual de desconto (1-100)
        expiration_days (int): Dias até a expiração do desconto
        applicable_plans (list, optional): Lista de planos aos quais o desconto se aplica. 
                                         Se None, aplica a todos os planos.
    
    Returns:
        str: ID do desconto criado
    """
    try:
        discount_id = str(uuid.uuid4())
        bot_config = read_json_file(BOT_CONFIG_FILE)
        
        # Inicializar a seção de descontos se não existir
        if 'seasonal_discounts' not in bot_config:
            bot_config['seasonal_discounts'] = {}
            
        # Calcular a data de expiração
        expiration_date = datetime.now() + timedelta(days=expiration_days)
        
        # Definir os planos aplicáveis
        if applicable_plans is None:
            applicable_plans = list(PLANS.keys())
            
        # Criar o desconto
        bot_config['seasonal_discounts'][discount_id] = {
            'discount_percent': discount_percent,
            'expiration_date': expiration_date.isoformat(),
            'applicable_plans': applicable_plans,
            'created_at': datetime.now().isoformat()
        }
        
        # Salvar as alterações
        write_json_file(BOT_CONFIG_FILE, bot_config)
        
        return discount_id
    except Exception as e:
        logger.error(f"Error adding seasonal discount: {e}")
        return None
        
def remove_seasonal_discount(discount_id):
    """
    Remove um desconto sazonal.
    
    Args:
        discount_id (str): ID do desconto a ser removido
    
    Returns:
        bool: True se o desconto foi removido com sucesso, False caso contrário
    """
    try:
        bot_config = read_json_file(BOT_CONFIG_FILE)
        
        # Verificar se a seção de descontos existe
        if 'seasonal_discounts' not in bot_config:
            return False
            
        # Verificar se o desconto existe
        if discount_id not in bot_config['seasonal_discounts']:
            return False
            
        # Remover o desconto
        del bot_config['seasonal_discounts'][discount_id]
        
        # Salvar as alterações
        write_json_file(BOT_CONFIG_FILE, bot_config)
        
        return True
    except Exception as e:
        logger.error(f"Error removing seasonal discount: {e}")
        return False

def get_active_seasonal_discounts():
    """
    Retorna todos os descontos sazonais ativos.
    
    Returns:
        dict: Dicionário com os descontos ativos
    """
    try:
        bot_config = read_json_file(BOT_CONFIG_FILE)
        
        # Verificar se a seção de descontos existe
        if 'seasonal_discounts' not in bot_config:
            return {}
            
        active_discounts = {}
        current_time = datetime.now()
        
        # Filtrar descontos ativos
        for discount_id, discount_data in bot_config['seasonal_discounts'].items():
            expiration_date = datetime.fromisoformat(discount_data['expiration_date'])
            if current_time < expiration_date:
                active_discounts[discount_id] = discount_data
                
        return active_discounts
    except Exception as e:
        logger.error(f"Error getting active seasonal discounts: {e}")
        return {}

def create_user(user_id, username, first_name, last_name=None, referred_by=None):
    user_data = {
        'username': username,
        'first_name': first_name,
        'last_name': last_name,
        'created_at': datetime.now().isoformat(),
        'has_active_plan': False,
        'plan_type': None,
        'plan_expiration': None,
        'login_info': None,
        'is_first_buy': True,
        'referrals': [],
        'referred_by': referred_by,
        'successful_referrals': 0
    }
    save_user(user_id, user_data)
    return user_data

# Payment management functions
def create_payment(user_id, plan_type, amount, coupon_code=None):
    payment_id = str(uuid.uuid4())
    payments = read_json_file(PAYMENTS_FILE)
    
    # Obter o timestamp atual para o momento de criação
    current_time = datetime.now()
    
    # Verificar se o usuário já tem pagamentos pendentes e cancelá-los
    for existing_payment_id, payment in list(payments.items()):
        if payment['user_id'] == str(user_id) and payment['status'] == 'pending':
            logger.info(f"Cancelando pagamento pendente existente {existing_payment_id} para o usuário {user_id}")
            
            # Se for um pagamento do Mercado Pago, cancelar na API
            if payment.get('mp_payment_id'):
                try:
                    _cancel_mercado_pago_payment(payment.get('mp_payment_id'))
                    logger.info(f"Pagamento Mercado Pago {payment.get('mp_payment_id')} cancelado ao criar novo pagamento")
                except Exception as e:
                    logger.error(f"Erro ao cancelar pagamento Mercado Pago existente: {e}")
            
            # Atualizar o status para cancelado
            payment['status'] = 'cancelled'
            payment['cancelled_at'] = current_time.isoformat()
            payment['cancelled_reason'] = 'Substituído por novo pagamento'
            payments[existing_payment_id] = payment
    
    payment_data = {
        'payment_id': payment_id,
        'user_id': str(user_id),
        'plan_type': plan_type,
        'amount': amount,
        'original_amount': amount,
        'coupon_code': coupon_code,
        'status': 'pending',
        'created_at': current_time.isoformat(),
        'approved_at': None,
        'payer_name': '',
        'login_delivered': False,
        'expiration_notified': False, # Para evitar notificações duplicadas de expiração
        'related_messages': [] # Lista de mensagens relacionadas (chat_id, message_id)
    }
    
    payments[payment_id] = payment_data
    write_json_file(PAYMENTS_FILE, payments)
    return payment_id

def get_payment(payment_id):
    payments = read_json_file(PAYMENTS_FILE)
    return payments.get(payment_id)

def update_payment(payment_id, data):
    payments = read_json_file(PAYMENTS_FILE)
    if payment_id in payments:
        payments[payment_id].update(data)
        write_json_file(PAYMENTS_FILE, payments)
        return True
    return False

def get_user_pending_payment(user_id):
    """
    Retorna o pagamento pendente de um usuário, se existir.
    Também verifica se o pagamento expirou (10 minutos) e cancela se necessário.
    
    Args:
        user_id (str): ID do usuário no Telegram
    
    Returns:
        dict: Dados do pagamento pendente ou None
    """
    payments = read_json_file(PAYMENTS_FILE)
    current_time = datetime.now()
    
    for payment_id, payment in payments.items():
        if payment['user_id'] == str(user_id) and payment['status'] == 'pending':
            # Verificar se o pagamento expirou (10 minutos)
            if 'created_at' in payment:
                created_at = datetime.fromisoformat(payment['created_at'])
                expiration_time = created_at + timedelta(minutes=10)
                
                if current_time > expiration_time:
                    # Pagamento expirou
                    payment['status'] = 'expired'
                    
                    # Se for um pagamento do Mercado Pago, cancelar na API
                    if payment.get('mp_payment_id'):
                        try:
                            _cancel_mercado_pago_payment(payment.get('mp_payment_id'))
                        except Exception as e:
                            logger.error(f"Erro ao cancelar pagamento expirado no Mercado Pago: {e}")
                    
                    # Salvar alteração
                    payments[payment_id] = payment
                    write_json_file(PAYMENTS_FILE, payments)
                    return None
            
            # Pagamento pendente válido
            payment['payment_id'] = payment_id
            return payment
    
    return None

def _cancel_mercado_pago_payment(mp_payment_id):
    """
    Função auxiliar para cancelar um pagamento no Mercado Pago
    
    Args:
        mp_payment_id (str): ID do pagamento no Mercado Pago
    
    Returns:
        bool: True se o cancelamento foi bem-sucedido, False caso contrário
    """
    try:
        import requests
        import uuid
        import logging
        import json
        
        # Obter configurações do Mercado Pago
        bot_config = read_json_file(BOT_CONFIG_FILE)
        mp_settings = bot_config.get('payment_settings', {}).get('mercado_pago', {})
        access_token = mp_settings.get('access_token')
        
        if not access_token:
            logging.warning("Não foi possível cancelar pagamento MP: token não encontrado")
            return False
        
        # Configurar headers
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": str(uuid.uuid4())
        }
        
        # Primeiro verificar status atual
        status_response = requests.get(
            f"https://api.mercadopago.com/v1/payments/{mp_payment_id}",
            headers=headers
        )
        
        if status_response.status_code == 200:
            payment_data = status_response.json()
            current_status = payment_data.get('status')
            
            # Só cancelar se estiver em um estado que permite cancelamento
            if current_status in ['pending', 'in_process', 'authorized']:
                cancel_data = {"status": "cancelled"}
                cancel_response = requests.put(
                    f"https://api.mercadopago.com/v1/payments/{mp_payment_id}",
                    headers=headers,
                    json=cancel_data
                )
                
                if cancel_response.status_code in [200, 201]:
                    logging.info(f"Pagamento Mercado Pago {mp_payment_id} cancelado com sucesso")
                    return True
                else:
                    logging.warning(f"Falha ao cancelar pagamento Mercado Pago {mp_payment_id}: {cancel_response.status_code}")
            else:
                logging.info(f"Pagamento Mercado Pago {mp_payment_id} já está em estado final: {current_status}")
        else:
            logging.warning(f"Falha ao obter status do pagamento Mercado Pago: {status_response.status_code}")
        
        return False
    except Exception as e:
        logging.error(f"Erro ao cancelar pagamento Mercado Pago: {e}")
        return False

def cancel_payment(payment_id):
    """
    Cancela um pagamento e limpa recursos associados (como QR codes do Mercado Pago)
    
    Args:
        payment_id (str): ID do pagamento a ser cancelado
        
    Returns:
        tuple: (bool, dict) Tupla com resultado da operação e dados do pagamento.
               O primeiro elemento é True se o cancelamento foi bem-sucedido, False caso contrário.
               O segundo elemento são os dados do pagamento ou None se não encontrado.
    """
    payments = read_json_file(PAYMENTS_FILE)
    if payment_id in payments:
        payment = payments[payment_id]
        
        # Se for um pagamento do Mercado Pago, tenta cancelar na API
        if payment.get('mp_payment_id'):
            _cancel_mercado_pago_payment(payment['mp_payment_id'])
        
        # Marca como cancelado no nosso sistema independente do resultado
        payment['status'] = 'cancelled'
        payments[payment_id] = payment
        write_json_file(PAYMENTS_FILE, payments)
        return True, payment
    
    return False, None

# Login management functions
def add_login(plan_type, login_data):
    logins = read_json_file(LOGINS_FILE)
    if plan_type in logins:
        logins[plan_type].append(login_data)
        write_json_file(LOGINS_FILE, logins)
        return True
    return False

def get_available_login(plan_type):
    logins = read_json_file(LOGINS_FILE)
    if plan_type in logins and logins[plan_type]:
        return logins[plan_type][0]
    return None

def remove_login(plan_type, login_data):
    logins = read_json_file(LOGINS_FILE)
    if plan_type in logins and login_data in logins[plan_type]:
        logins[plan_type].remove(login_data)
        write_json_file(LOGINS_FILE, logins)
        return True
    return False

def assign_login_to_user(user_id, plan_type, payment_id):
    user = get_user(user_id)
    login = get_available_login(plan_type)
    
    if not user:
        logger.error(f"User {user_id} not found")
        return False
    
    if not login:
        logger.error(f"No available login for plan type {plan_type}")
        return False
    
    # Update user with the login and plan information
    plan_info = PLANS[plan_type]
    expiration_date = datetime.now() + timedelta(days=plan_info['duration_days'])
    
    user['has_active_plan'] = True
    user['plan_type'] = plan_type
    user['plan_expiration'] = expiration_date.isoformat()
    user['login_info'] = login
    user['is_first_buy'] = False
    
    save_user(user_id, user)
    
    # Update payment status
    update_payment(payment_id, {
        'status': 'completed',
        'approved_at': datetime.now().isoformat(),
        'login_delivered': True
    })
    
    # Remove the login from available logins
    remove_login(plan_type, login)
    
    # Process referral if applicable
    if user['referred_by']:
        process_successful_referral(user['referred_by'])
    
    return login

def process_successful_referral(referrer_id):
    referrer = get_user(referrer_id)
    if referrer:
        referrer['successful_referrals'] = referrer.get('successful_referrals', 0) + 1
        save_user(referrer_id, referrer)
        
        # Check if referrer qualifies for free month
        bot_config = read_json_file(BOT_CONFIG_FILE)
        required_referrals = bot_config['referral_rewards']['free_month_after_referrals']
        
        if referrer['successful_referrals'] % required_referrals == 0:
            # Will be used by the bot to notify about free month
            return True
    
    return False

# Check for pending logins and users waiting for logins
def get_pending_approvals():
    payments = read_json_file(PAYMENTS_FILE)
    pending_approvals = []
    
    for payment_id, payment in payments.items():
        if payment['status'] == 'pending' and payment.get('payer_name'):
            pending_approvals.append(payment)
    
    return pending_approvals

def get_users_waiting_for_login():
    payments = read_json_file(PAYMENTS_FILE)
    waiting_users = []
    
    for payment_id, payment in payments.items():
        if payment['status'] == 'approved' and not payment['login_delivered']:
            waiting_users.append(payment)
    
    return waiting_users

# Functions to check and update sales status
def check_should_suspend_sales():
    logins = read_json_file(LOGINS_FILE)
    total_logins = sum(len(logins[plan_type]) for plan_type in logins)
    
    if total_logins == 0:
        return True
    
    return False

def suspend_sales():
    bot_config = read_json_file(BOT_CONFIG_FILE)
    bot_config['sales_enabled'] = False
    bot_config['sales_suspended_time'] = datetime.now().isoformat()
    write_json_file(BOT_CONFIG_FILE, bot_config)

def resume_sales():
    bot_config = read_json_file(BOT_CONFIG_FILE)
    bot_config['sales_enabled'] = True
    bot_config['sales_suspended_time'] = None
    bot_config['warning_sent'] = False
    write_json_file(BOT_CONFIG_FILE, bot_config)

def sales_enabled():
    bot_config = read_json_file(BOT_CONFIG_FILE)
    return bot_config.get('sales_enabled', True)

# Coupon management functions
def add_coupon(code, discount_type, discount_value, expiration_date, max_uses, max_uses_per_user, min_purchase, applicable_plans):
    """
    Adiciona um novo cupom de desconto ao sistema.
    
    Args:
        code (str): Código do cupom
        discount_type (str): Tipo de desconto ('percentage' ou 'fixed')
        discount_value (float): Valor do desconto
        expiration_date (str): Data de expiração em formato ISO
        max_uses (int): Máximo de usos totais (-1 para ilimitado)
        max_uses_per_user (int): Máximo de usos por usuário (-1 para ilimitado)
        min_purchase (float): Valor mínimo de compra para aplicar o cupom
        applicable_plans (list): Lista de planos aplicáveis
    
    Returns:
        tuple: (bool, str) Sucesso e mensagem
    """
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    # Convert to uppercase for consistency
    code = code.upper()
    
    # Check if coupon already exists
    if code in bot_config.get('coupons', {}):
        return False, "Cupom já existe."
    
    # Check valid discount value
    if discount_type == 'percentage' and (discount_value <= 0 or discount_value >= 100):
        return False, "Valor de desconto percentual deve estar entre 1 e 99."
    
    if discount_type == 'fixed' and discount_value <= 0:
        return False, "Valor de desconto fixo deve ser maior que zero."
    
    # Don't allow 100% discount
    if discount_type == 'percentage' and discount_value == 100:
        return False, "Cupons com 100% de desconto não são permitidos."
    
    # Create the coupon
    coupon = {
        'code': code,
        'discount_type': discount_type,
        'discount_value': discount_value,
        'expiration_date': expiration_date,
        'max_uses': max_uses,
        'max_uses_per_user': max_uses_per_user,
        'min_purchase': min_purchase,
        'applicable_plans': applicable_plans,
        'uses': 0,
        'usage_history': {} # Formato: {"user_id": count}
    }
    
    if 'coupons' not in bot_config:
        bot_config['coupons'] = {}
    
    bot_config['coupons'][code] = coupon
    write_json_file(BOT_CONFIG_FILE, bot_config)
    
    return True, "Cupom criado com sucesso."

def validate_coupon(code, user_id, plan_type, amount):
    if not code:
        return None, "Código de cupom não fornecido."
    
    code = code.upper()
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    if 'coupons' not in bot_config or code not in bot_config['coupons']:
        return None, "Cupom não encontrado."
    
    coupon = bot_config['coupons'][code]
    
    # Check expiration
    if coupon['expiration_date']:
        expiration_date = datetime.fromisoformat(coupon['expiration_date'])
        if datetime.now() > expiration_date:
            return None, "Este cupom expirou."
    
    # Check max uses
    if coupon['max_uses'] != -1 and coupon['uses'] >= coupon['max_uses']:
        return None, "Este cupom atingiu o limite máximo de usos."
    
    # Verificar limite de usos por usuário
    user_id_str = str(user_id)
    
    if 'usage_history' in coupon:
        # Nova estrutura de contagem de usos
        user_usage_count = coupon['usage_history'].get(user_id_str, 0)
        if coupon['max_uses_per_user'] != -1 and user_usage_count >= coupon['max_uses_per_user']:
            return None, f"Você já atingiu o limite máximo de {coupon['max_uses_per_user']} uso(s) deste cupom."
    else:
        # Compatibilidade com a estrutura antiga (apenas verifica se já usou)
        if str(user_id) in coupon.get('users', []):
            return None, "Você já utilizou este cupom anteriormente."
    
    # Check minimum purchase
    if coupon['min_purchase'] and amount < coupon['min_purchase']:
        return None, f"Valor mínimo para uso do cupom é R$ {coupon['min_purchase']:.2f}."
    
    # Check applicable plans
    if 'all' not in coupon['applicable_plans'] and plan_type not in coupon['applicable_plans']:
        return None, "Este cupom não é válido para o plano selecionado."
    
    # Check if it's the user's first purchase
    user = get_user(user_id)
    if user and user.get('is_first_buy', True):
        return None, "Cupons não podem ser usados na primeira compra."
    
    # Calculate discount
    if coupon['discount_type'] == 'percentage':
        discount = amount * (coupon['discount_value'] / 100)
    else:  # fixed
        discount = coupon['discount_value']
    
    # Ensure discount doesn't make price negative
    if amount - discount <= 0:
        discount = amount - 0.01  # Leave minimal price to pay
    
    return {
        'code': code,
        'discount': discount,
        'final_amount': amount - discount
    }, "Cupom aplicado com sucesso!"

def use_coupon(code, user_id):
    """
    Registra o uso de um cupom por um usuário.
    
    Args:
        code (str): Código do cupom
        user_id (str): ID do usuário que utilizou o cupom
    
    Returns:
        bool: True se o cupom foi utilizado com sucesso, False caso contrário
    """
    user_id_str = str(user_id)
    code = code.upper()
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    if 'coupons' in bot_config and code in bot_config['coupons']:
        coupon = bot_config['coupons'][code]
        
        # Incrementar contador global de usos
        coupon['uses'] += 1
        
        # Verificar se estamos usando o novo formato de rastreamento
        if 'usage_history' in coupon:
            # Incrementar uso para esse usuário específico
            if user_id_str in coupon['usage_history']:
                coupon['usage_history'][user_id_str] += 1
            else:
                coupon['usage_history'][user_id_str] = 1
        else:
            # Compatibilidade com sistema antigo
            if 'users' not in coupon:
                coupon['users'] = []
            if user_id_str not in coupon['users']:
                coupon['users'].append(user_id_str)
                
            # Criar o campo usage_history para migração gradual
            coupon['usage_history'] = {}
            for user in coupon['users']:
                coupon['usage_history'][user] = 1
        
        write_json_file(BOT_CONFIG_FILE, bot_config)
        logger.info(f"Coupon {code} used by user {user_id_str}. Total uses: {coupon['uses']}")
        return True
    
    return False

def delete_coupon(code):
    code = code.upper()
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    if 'coupons' in bot_config and code in bot_config['coupons']:
        del bot_config['coupons'][code]
        write_json_file(BOT_CONFIG_FILE, bot_config)
        return True
    
    return False

# Check for expiring subscriptions
def get_expiring_subscriptions(days_threshold=3):
    users = read_json_file(USERS_FILE)
    expiring_users = []
    
    for user_id, user_data in users.items():
        if user_data.get('has_active_plan') and user_data.get('plan_expiration'):
            expiration_date = datetime.fromisoformat(user_data['plan_expiration'])
            days_left = (expiration_date - datetime.now()).days
            
            if 0 < days_left <= days_threshold:
                expiring_users.append({
                    'user_id': user_id,
                    'days_left': days_left,
                    'plan_type': user_data['plan_type'],
                    'expiration_date': user_data['plan_expiration']
                })
    
    return expiring_users

# Format currency values
def format_currency(value):
    return f"R$ {value:.2f}".replace('.', ',')

# Calculate price based on user status and plan
def get_seasonal_discount_info(plan_type):
    """
    Verifica se há descontos sazonais ativos para um plano específico.
    
    Args:
        plan_type (str): O tipo de plano (ex: '30_days', '6_months', '1_year')
    
    Returns:
        tuple: (discount_percent, expiration_date, discount_id) ou (None, None, None) se não houver desconto
    """
    try:
        # Obter descontos sazonais ativos
        active_discounts = get_active_seasonal_discounts()
        
        # Verificar se há descontos aplicáveis ao plano específico
        for discount_id, discount in active_discounts.items():
            applicable_plans = discount.get('applicable_plans', [])
            
            # Verificar se o desconto se aplica a este plano
            if not applicable_plans or plan_type in applicable_plans:
                return (
                    discount['discount_percent'],
                    datetime.fromisoformat(discount['expiration_date']),
                    discount_id
                )
        
        return None, None, None
    except Exception as e:
        logger.error(f"Erro ao verificar descontos sazonais: {e}")
        return None, None, None

def calculate_plan_price(user_id, plan_type):
    """
    Calcula o preço de um plano considerando descontos para primeira compra e descontos sazonais.
    
    Args:
        user_id (str): ID do usuário no Telegram
        plan_type (str): Tipo de plano ('30_days', '6_months', '1_year')
    
    Returns:
        float: Preço final do plano após aplicar descontos
        dict: Informações sobre o desconto sazonal (se aplicado) ou None
    """
    user = get_user(user_id)
    plan = PLANS[plan_type]
    base_price = None
    discount_info = {}
    
    # Check if user is eligible for first-time buyer discount
    if user and user.get('is_first_buy') and plan['first_buy_discount']:
        base_price = plan['first_buy_price']
        discount_info['first_buy_discount'] = True
    else:
        base_price = plan['regular_price']
    
    # Check if there are any seasonal discounts applicable
    discount_percent, expiration_date, discount_id = get_seasonal_discount_info(plan_type)
    
    if discount_percent is not None:
        # Aplicar desconto sazonal
        discounted_price = base_price * (1 - discount_percent / 100)
        discount_info['seasonal_discount'] = {
            'percent': discount_percent,
            'expiration_date': expiration_date,
            'discount_id': discount_id,
            'original_price': base_price,
            'discounted_price': discounted_price
        }
        return discounted_price, discount_info
    
    return base_price, discount_info

# Apply referral discount if applicable
def apply_referral_discount(user_id, amount):
    user = get_user(user_id)
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    if not user or user.get('is_first_buy'):
        return amount, False
    
    referrer_discount = bot_config['referral_rewards']['referrer_discount']
    
    # Check if this user was referred and it's their first non-first purchase
    if user.get('referred_by') and not user.get('referral_discount_applied'):
        # Apply discount
        discount = (referrer_discount / 100) * amount
        final_amount = amount - discount
        
        # Mark as applied
        user['referral_discount_applied'] = True
        save_user(user_id, user)
        
        return final_amount, True
    
    return amount, False

# Telegram Authentication Functions
def is_admin_telegram_id(telegram_id):
    """Check if a Telegram ID is an admin"""
    auth_data = read_json_file(AUTH_FILE)
    return str(telegram_id) in auth_data.get('admin_telegram_ids', [])

def is_allowed_telegram_id(telegram_id):
    """Check if a Telegram ID is allowed to access the admin panel"""
    auth_data = read_json_file(AUTH_FILE)
    return (str(telegram_id) in auth_data.get('allowed_telegram_ids', []) or 
            is_admin_telegram_id(telegram_id))

def add_allowed_telegram_id(telegram_id):
    """Add a Telegram ID to the allowed list"""
    auth_data = read_json_file(AUTH_FILE)
    telegram_id = str(telegram_id)
    
    if 'allowed_telegram_ids' not in auth_data:
        auth_data['allowed_telegram_ids'] = []
    
    if telegram_id not in auth_data['allowed_telegram_ids']:
        auth_data['allowed_telegram_ids'].append(telegram_id)
        write_json_file(AUTH_FILE, auth_data)
        return True
    
    return False

def remove_allowed_telegram_id(telegram_id):
    """Remove a Telegram ID from the allowed list"""
    auth_data = read_json_file(AUTH_FILE)
    telegram_id = str(telegram_id)
    
    if 'allowed_telegram_ids' in auth_data and telegram_id in auth_data['allowed_telegram_ids']:
        auth_data['allowed_telegram_ids'].remove(telegram_id)
        write_json_file(AUTH_FILE, auth_data)
        return True
    
    return False

# Session Management Functions
def create_session(telegram_id, user_data=None):
    """Create a new session for a user"""
    try:
        # Gerar token único
        session_token = secrets.token_hex(32)
        
        # Ler sessões existentes ou inicializar
        sessions = read_json_file(SESSION_FILE)
        if sessions is None:
            sessions = {}
        
        # Preparar dados do usuário
        if not user_data:
            # Verificar se o usuário existe, se não, criar dados básicos
            user = get_user(telegram_id)
            if user:
                user_data = {
                    'first_name': user.get('first_name', 'Admin'),
                    'username': user.get('username', f'User{telegram_id}')
                }
            else:
                # Usuário não encontrado, usar dados básicos
                user_data = {
                    'first_name': 'Admin',
                    'username': f'User{telegram_id}'
                }
        
        # Garantir que o user_data não seja None
        if user_data is None:
            user_data = {
                'first_name': 'Admin',
                'username': f'User{telegram_id}'
            }
        
        # Registrar o login
        logger.debug(f"Creating session for telegram_id: {telegram_id}, with data: {user_data}")
        
        # Create session
        sessions[session_token] = {
            'telegram_id': str(telegram_id),
            'created_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(hours=SESSION_EXPIRY_HOURS)).isoformat(),
            'user_data': user_data
        }
        
        # Salvar as sessões no arquivo
        write_success = write_json_file(SESSION_FILE, sessions)
        
        if not write_success:
            logger.error(f"Failed to write session file for telegram_id: {telegram_id}")
            # Se falhar ao salvar, ainda retornamos o token para não interromper o login
        
        return session_token
    except Exception as e:
        logger.error(f"Error creating session for telegram_id {telegram_id}: {e}")
        # Último recurso - retornar um token temporário para não interromper o login
        return secrets.token_hex(32)

def get_session(session_token):
    """Get a session by token"""
    try:
        # Verificar se o token é válido
        if not session_token:
            logger.warning("Attempted to get session with empty token")
            return None
        
        # Ler as sessões do arquivo
        sessions = read_json_file(SESSION_FILE)
        if sessions is None:
            logger.error("Sessions file returned None")
            return None
            
        # Verificar se o token existe nas sessões
        session = sessions.get(session_token)
        if not session:
            logger.warning(f"Session token not found: {session_token[:8]}...")
            return None
        
        # Verificar se a sessão tem o campo obrigatório expires_at
        if 'expires_at' not in session:
            logger.error(f"Session missing expires_at field: {session_token[:8]}...")
            return None
        
        # Verificar se a sessão expirou
        try:
            expires_at = datetime.fromisoformat(session['expires_at'])
            if datetime.now() > expires_at:
                logger.info(f"Session expired: {session_token[:8]}...")
                delete_session(session_token)
                return None
        except ValueError as e:
            logger.error(f"Invalid date format in session: {e}")
            return None
        
        # Se chegou até aqui, a sessão é válida
        return session
    except Exception as e:
        logger.error(f"Error in get_session: {e}")
        return None

def delete_session(session_token):
    """Delete a session"""
    try:
        # Verificar se o token é válido
        if not session_token:
            logger.warning("Attempted to delete session with empty token")
            return False
            
        # Ler as sessões do arquivo
        sessions = read_json_file(SESSION_FILE)
        if sessions is None:
            logger.error("Sessions file returned None when trying to delete session")
            return False
        
        # Verificar se o token existe nas sessões
        if session_token in sessions:
            # Registrar a exclusão
            logger.debug(f"Deleting session: {session_token[:8]}...")
            
            # Remover a sessão
            del sessions[session_token]
            
            # Salvar o arquivo de sessões atualizado
            write_success = write_json_file(SESSION_FILE, sessions)
            if not write_success:
                logger.error(f"Failed to write sessions file when deleting token: {session_token[:8]}...")
                return False
            
            return True
        else:
            logger.warning(f"Session token not found for deletion: {session_token[:8]}...")
            return False
    except Exception as e:
        logger.error(f"Error in delete_session: {e}")
        return False

def clean_expired_sessions():
    """Remove all expired sessions"""
    try:
        # Ler as sessões do arquivo
        sessions = read_json_file(SESSION_FILE)
        if sessions is None or not sessions:
            logger.warning("No sessions found to clean")
            return 0
        
        now = datetime.now()
        session_tokens_to_delete = []
        
        # Identificar sessões expiradas
        for token, session in sessions.items():
            try:
                if 'expires_at' in session:
                    expires_at = datetime.fromisoformat(session['expires_at'])
                    if now > expires_at:
                        session_tokens_to_delete.append(token)
                        logger.debug(f"Marked expired session for deletion: {token[:8]}...")
                else:
                    # Sessão sem data de expiração está inválida
                    session_tokens_to_delete.append(token)
                    logger.warning(f"Session without expiration date marked for deletion: {token[:8]}...")
            except (ValueError, TypeError) as e:
                # Erro ao processar a data de expiração
                session_tokens_to_delete.append(token)
                logger.error(f"Error processing expiration date for session {token[:8]}...: {e}")
        
        # Remover as sessões expiradas
        for token in session_tokens_to_delete:
            try:
                del sessions[token]
            except KeyError:
                logger.error(f"Failed to delete session {token[:8]}...")
        
        # Salvar as alterações se houve remoção de sessões
        if session_tokens_to_delete:
            write_success = write_json_file(SESSION_FILE, sessions)
            if not write_success:
                logger.error("Failed to write sessions file after cleaning expired sessions")
        
        # Registrar o número de sessões removidas
        cleaned_count = len(session_tokens_to_delete)
        if cleaned_count > 0:
            logger.info(f"Cleaned {cleaned_count} expired sessions")
        
        return cleaned_count
    except Exception as e:
        logger.error(f"Error in clean_expired_sessions: {e}")
        return 0

# Authentication token functions
def create_auth_token(telegram_id):
    """Create a one-time authentication token for a Telegram user"""
    # Generate a secure random token
    token = secrets.token_hex(16)
    
    # Create hash of the token to store
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Get current user data
    user = get_user(telegram_id)
    
    if user:
        # Update user with token hash and expiration
        user['auth_token'] = {
            'hash': token_hash,
            'expires_at': (datetime.now() + timedelta(minutes=10)).isoformat()
        }
        save_user(telegram_id, user)
        
        return token
    
    return None

def verify_auth_token(telegram_id, token):
    """Verify a one-time authentication token"""
    user = get_user(telegram_id)
    
    if not user or 'auth_token' not in user:
        return False
    
    token_data = user['auth_token']
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Check if token has expired
    expires_at = datetime.fromisoformat(token_data['expires_at'])
    if datetime.now() > expires_at:
        # Clear expired token
        user.pop('auth_token', None)
        save_user(telegram_id, user)
        return False
    
    # Check if token hash matches
    if token_hash == token_data['hash']:
        # Clear used token
        user.pop('auth_token', None)
        save_user(telegram_id, user)
        return True
    
    return False

# Functions to check admin and allowed user status
def is_admin_telegram_id(telegram_id):
    """Check if a Telegram ID is an admin"""
    auth_data = read_json_file(AUTH_FILE)
    
    # Convert to string for comparison since JSON keys are strings
    telegram_id = str(telegram_id)
    
    # Check primary admin ID from environment variable
    if telegram_id == str(ADMIN_ID):
        return True
    
    # Check admin list in auth.json
    if 'admin_telegram_ids' in auth_data:
        return telegram_id in auth_data['admin_telegram_ids']
        
    return False

def is_root_admin(telegram_id):
    """Check if a Telegram ID is the root admin (set in .env)"""
    if telegram_id is None:
        return False
        
    # Convert to string for comparison - com validação adicional
    try:
        telegram_id_str = str(telegram_id).strip()
        admin_id_str = str(ADMIN_ID).strip()
        
        # Log para debug
        logger.debug(f"is_root_admin: Comparing telegram_id={telegram_id_str} with ADMIN_ID={admin_id_str}")
        
        # Verificação detalhada
        is_root = telegram_id_str == admin_id_str
        logger.debug(f"is_root_admin result: {is_root}")
        return is_root
    except Exception as e:
        logger.error(f"Error in is_root_admin: {e}")
        # Em caso de erro, verificar diretamente com o valor bruto para maior segurança
        return str(telegram_id) == str(ADMIN_ID)

def is_allowed_telegram_id(telegram_id):
    """Check if a Telegram ID is allowed to access the admin panel"""
    # Admins always have access
    if is_admin_telegram_id(telegram_id):
        return True
    
    auth_data = read_json_file(AUTH_FILE)
    
    # Convert to string for comparison since JSON keys are strings
    telegram_id = str(telegram_id)
    
    # Check allowed user list
    if 'allowed_telegram_ids' in auth_data:
        return telegram_id in auth_data['allowed_telegram_ids']
        
    return False

def add_admin_telegram_id(telegram_id):
    """Add a Telegram ID to the admin list (can only be done by root admin)"""
    auth_data = read_json_file(AUTH_FILE)
    
    # Convert to string for storage consistency
    telegram_id = str(telegram_id)
    
    # Ensure the admin_telegram_ids list exists
    if 'admin_telegram_ids' not in auth_data:
        auth_data['admin_telegram_ids'] = []
    
    # Add to admin list if not already there
    if telegram_id not in auth_data['admin_telegram_ids'] and telegram_id != str(ADMIN_ID):
        auth_data['admin_telegram_ids'].append(telegram_id)
        write_json_file(AUTH_FILE, auth_data)
        return True
    
    return False

def remove_admin_telegram_id(telegram_id):
    """Remove a Telegram ID from the admin list (can only be done by root admin)"""
    auth_data = read_json_file(AUTH_FILE)
    
    # Convert to string for storage consistency
    telegram_id = str(telegram_id)
    
    # Cannot remove root admin
    if telegram_id == str(ADMIN_ID):
        return False
    
    # Ensure the admin_telegram_ids list exists
    if 'admin_telegram_ids' not in auth_data:
        return False
    
    # Remove from admin list if present
    if telegram_id in auth_data['admin_telegram_ids']:
        auth_data['admin_telegram_ids'].remove(telegram_id)
        write_json_file(AUTH_FILE, auth_data)
        return True
    
    return False

def add_allowed_telegram_id(telegram_id):
    """Add a Telegram ID to the allowed list"""
    auth_data = read_json_file(AUTH_FILE)
    
    # Convert to string for storage consistency
    telegram_id = str(telegram_id)
    
    # Check if it's already an admin
    if is_admin_telegram_id(telegram_id):
        return False
    
    # Ensure the allowed_telegram_ids list exists
    if 'allowed_telegram_ids' not in auth_data:
        auth_data['allowed_telegram_ids'] = []
    
    # Add to allowed list if not already there
    if telegram_id not in auth_data['allowed_telegram_ids']:
        auth_data['allowed_telegram_ids'].append(telegram_id)
        write_json_file(AUTH_FILE, auth_data)
        return True
        
    return False

def remove_allowed_telegram_id(telegram_id):
    """Remove a Telegram ID from the allowed list"""
    auth_data = read_json_file(AUTH_FILE)
    
    # Convert to string for consistency
    telegram_id = str(telegram_id)
    
    # Cannot remove admins
    if is_admin_telegram_id(telegram_id):
        return False
    
    # Remove from allowed list if present
    if 'allowed_telegram_ids' in auth_data and telegram_id in auth_data['allowed_telegram_ids']:
        auth_data['allowed_telegram_ids'].remove(telegram_id)
        write_json_file(AUTH_FILE, auth_data)
        return True
        
    return False

# Access code functions for admin panel login
def generate_access_code(telegram_id, expiration_hours=24):
    """
    Generate a unique access code for a Telegram ID
    
    This creates a 6-character alphanumeric code that can be used for login
    This code is stored in the auth.json file and expires after a set time
    """
    # Generate a random 6-character code
    code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
    
    # Convert to string for storage
    telegram_id = str(telegram_id)
    
    auth_data = read_json_file(AUTH_FILE)
    
    # Initialize access_codes dict if it doesn't exist
    if 'access_codes' not in auth_data:
        auth_data['access_codes'] = {}
    
    # Check if user already has previous codes and remove them
    for existing_code in list(auth_data['access_codes'].keys()):
        if auth_data['access_codes'][existing_code].get('telegram_id') == telegram_id:
            del auth_data['access_codes'][existing_code]
    
    # Store the code with expiration time
    auth_data['access_codes'][code] = {
        'telegram_id': telegram_id,
        'created_at': datetime.now().isoformat(),
        'expires_at': (datetime.now() + timedelta(hours=expiration_hours)).isoformat()
    }
    
    write_json_file(AUTH_FILE, auth_data)
    
    return code

def verify_access_code(telegram_id, code):
    """
    Verify if an access code is valid for the given Telegram ID
    
    Returns True if the code is valid and not expired, False otherwise
    """
    import os
    import threading
    
    auth_data = read_json_file(AUTH_FILE)
    
    # Convert to string for comparison
    telegram_id = str(telegram_id)
    
    # Check if access_codes exists
    if 'access_codes' not in auth_data:
        return False
    
    # Check if code exists
    if code not in auth_data['access_codes']:
        return False
    
    # Get code data
    code_data = auth_data['access_codes'][code]
    
    # Check if telegram_id matches
    if code_data.get('telegram_id') != telegram_id:
        return False
    
    # Check if code is expired
    expires_at = datetime.fromisoformat(code_data['expires_at'])
    if datetime.now() > expires_at:
        # Remove expired code
        del auth_data['access_codes'][code]
        write_json_file(AUTH_FILE, auth_data)
        return False
    
    # Valid code - remove it after use (one-time use)
    # Salvar informações do código antes de removê-lo
    message_id = code_data.get('message_id')
    chat_id = telegram_id
    
    # Remove o código pois foi utilizado com sucesso
    del auth_data['access_codes'][code]
    write_json_file(AUTH_FILE, auth_data)
    
    # Editar a mensagem no Telegram informando que o voucher foi utilizado
    if message_id:
        def update_telegram_message():
            try:
                import requests
                bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
                if bot_token:
                    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
                    data = {
                        'chat_id': chat_id,
                        'message_id': message_id,
                        'text': f"🔐 *Acesso ao Painel Administrativo* 🔐\n\n"
                               f"✅ *CÓDIGO UTILIZADO COM SUCESSO* ✅\n\n"
                               f"O código `{code}` foi utilizado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}.\n"
                               f"Este código não pode mais ser utilizado.",
                        'parse_mode': 'Markdown'
                    }
                    requests.post(url, data=data)
            except Exception as e:
                print(f"Erro ao atualizar mensagem no Telegram: {e}")
        
        # Executar a edição da mensagem em uma thread separada para não bloquear o login
        threading.Thread(target=update_telegram_message).start()
    
    return True

def list_active_access_codes():
    """
    List all active access codes
    
    Returns a dictionary with code -> user info mapping
    Removes expired codes in the process
    """
    auth_data = read_json_file(AUTH_FILE)
    
    if 'access_codes' not in auth_data:
        auth_data['access_codes'] = {}
        return {}
    
    # Check for expired codes and remove them
    now = datetime.now()
    codes_to_remove = []
    
    for code, code_data in auth_data['access_codes'].items():
        expires_at = datetime.fromisoformat(code_data['expires_at'])
        if now > expires_at:
            codes_to_remove.append(code)
    
    # Remove expired codes
    for code in codes_to_remove:
        del auth_data['access_codes'][code]
    
    # If we removed any codes, update the file
    if codes_to_remove:
        write_json_file(AUTH_FILE, auth_data)
    
    # Return active codes
    active_codes = {}
    for code, code_data in auth_data['access_codes'].items():
        # Get user info
        user = get_user(code_data['telegram_id'])
        username = user.get('username', 'Unknown') if user else 'Unknown'
        
        active_codes[code] = {
            'telegram_id': code_data['telegram_id'],
            'username': username,
            'created_at': code_data['created_at'],
            'expires_at': code_data['expires_at']
        }
    
    return active_codes
