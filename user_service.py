import logging
import secrets
import hashlib
from datetime import datetime, timedelta

from config import USERS_FILE, PLANS, AUTH_FILE, SESSION_FILE, SESSION_EXPIRY_HOURS, BOT_CONFIG_FILE
from db_utils import read_json_file, write_json_file

# Configuração de logging
logger = logging.getLogger(__name__)

def get_user(user_id):
    """
    Obtém os dados de um usuário pelo seu ID do Telegram.
    
    Args:
        user_id (str): ID do usuário no Telegram
    
    Returns:
        dict: Dados do usuário ou None se não encontrado
    """
    users = read_json_file(USERS_FILE)
    return users.get(str(user_id))


def save_user(user_id, user_data):
    """
    Salva os dados de um usuário.
    
    Args:
        user_id (str): ID do usuário no Telegram
        user_data (dict): Dados do usuário a serem salvos
    
    Returns:
        bool: True se a operação foi bem-sucedida, False caso contrário
    """
    users = read_json_file(USERS_FILE)
    users[str(user_id)] = user_data
    return write_json_file(USERS_FILE, users)


def create_user(user_id, username, first_name, last_name=None, referred_by=None):
    """
    Cria um novo usuário.
    
    Args:
        user_id (str): ID do usuário no Telegram
        username (str): Nome de usuário no Telegram
        first_name (str): Primeiro nome
        last_name (str, optional): Sobrenome
        referred_by (str, optional): ID do usuário que fez a indicação
    
    Returns:
        dict: Dados do usuário criado
    """
    user_data = {
        'username': username,
        'first_name': first_name,
        'last_name': last_name,
        'created_at': datetime.now().isoformat(),
        'has_active_plan': False,
        'plan_type': None,
        'plan_expiration': None,
        'login_info': None,
        'is_banned': False,
        'ban_reason': None,
        'is_first_buy': True,
        'referrals': [],
        'successful_referrals': 0
    }
    
    if referred_by:
        user_data['referred_by'] = str(referred_by)
    
    save_user(user_id, user_data)
    return user_data


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
    user = get_user(user_id)
    if not user:
        logger.error(f"Usuário {user_id} não encontrado ao atribuir plano")
        return False
    
    if plan_type not in PLANS:
        logger.error(f"Tipo de plano inválido: {plan_type}")
        return False
    
    # Determinar duração do plano
    if duration_days is None:
        duration_days = PLANS[plan_type]['duration_days']
    
    # Calcular data de expiração
    expiration_date = datetime.now() + timedelta(days=duration_days)
    
    # Atualizar dados do usuário
    user['has_active_plan'] = True
    user['plan_type'] = plan_type
    user['plan_expiration'] = expiration_date.isoformat()
    user['expiration_notified'] = False
    
    return save_user(user_id, user)


def remove_plan_from_user(user_id):
    """
    Remove o plano atual de um usuário.
    
    Args:
        user_id (str): ID do usuário no Telegram
    
    Returns:
        bool: True se o plano foi removido com sucesso, False caso contrário
    """
    user = get_user(user_id)
    if not user:
        logger.error(f"Usuário {user_id} não encontrado ao remover plano")
        return False
    
    # Remover dados do plano
    user['has_active_plan'] = False
    user['plan_type'] = None
    user['plan_expiration'] = None
    user['login_info'] = None
    
    return save_user(user_id, user)


def ban_user(user_id, reason=None):
    """
    Bane um usuário, impedindo-o de usar o bot.
    
    Args:
        user_id (str): ID do usuário no Telegram
        reason (str, optional): Motivo do banimento
    
    Returns:
        bool: True se o usuário foi banido com sucesso, False caso contrário
    """
    user = get_user(user_id)
    if not user:
        logger.error(f"Usuário {user_id} não encontrado ao banir")
        return False
    
    # Marcar usuário como banido
    user['is_banned'] = True
    user['ban_reason'] = reason
    user['banned_at'] = datetime.now().isoformat()
    
    # Remover plano se tiver
    if user.get('has_active_plan'):
        user['has_active_plan'] = False
        user['plan_type'] = None
        user['plan_expiration'] = None
        user['login_info'] = None
    
    return save_user(user_id, user)


def unban_user(user_id):
    """
    Remove o banimento de um usuário.
    
    Args:
        user_id (str): ID do usuário no Telegram
    
    Returns:
        bool: True se o usuário foi desbanido com sucesso, False caso contrário
    """
    user = get_user(user_id)
    if not user:
        logger.error(f"Usuário {user_id} não encontrado ao desbanir")
        return False
    
    # Desbanir usuário
    user['is_banned'] = False
    user['ban_reason'] = None
    user['unbanned_at'] = datetime.now().isoformat()
    
    return save_user(user_id, user)


def process_successful_referral(referrer_id):
    """
    Processa uma indicação bem-sucedida.
    
    Args:
        referrer_id (str): ID do usuário que fez a indicação
    
    Returns:
        bool: True se o processamento foi bem-sucedido, False caso contrário
    """
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


def apply_referral_discount(user_id, amount):
    """
    Aplica desconto por indicação se o usuário tiver sido indicado.
    
    Args:
        user_id (str): ID do usuário no Telegram
        amount (float): Valor original
    
    Returns:
        tuple: (float, bool) - Valor com desconto (ou original) e flag indicando se um desconto foi aplicado
    """
    user = get_user(user_id)
    
    if not user or user.get('is_first_buy', True) or not user.get('referred_by'):
        return amount, False
    
    # Get referral rewards configuration
    bot_config = read_json_file(BOT_CONFIG_FILE)
    discount_percent = bot_config['referral_rewards']['referred_discount']
    
    # Apply discount
    discount = amount * (discount_percent / 100)
    discounted_amount = amount - discount
    
    return discounted_amount, True


def get_expiring_subscriptions(days_threshold=3):
    """
    Obtém assinaturas que estão prestes a expirar.
    
    Args:
        days_threshold (int): Número de dias para considerar como "prestes a expirar"
    
    Returns:
        list: Lista de usuários com assinaturas prestes a expirar
    """
    users = read_json_file(USERS_FILE)
    expiring_users = []
    current_date = datetime.now()
    
    for user_id, user in users.items():
        if user.get('has_active_plan') and user.get('plan_expiration'):
            # Calcular dias restantes
            expiration_date = datetime.fromisoformat(user['plan_expiration'])
            days_left = (expiration_date - current_date).days
            
            # Verificar se está dentro do limite
            if 0 < days_left <= days_threshold and not user.get('expiration_notified'):
                expiring_users.append({
                    'user_id': user_id,
                    'days_left': days_left,
                    'plan_type': user['plan_type']
                })
    
    return expiring_users


# Funções relacionadas à autenticação
def is_admin_telegram_id(telegram_id):
    """Check if a Telegram ID is an admin"""
    from config import ADMIN_ID
    return str(telegram_id) == str(ADMIN_ID)


def is_allowed_telegram_id(telegram_id):
    """Check if a Telegram ID is allowed to access the admin panel"""
    if is_admin_telegram_id(telegram_id):
        return True
    
    auth_data = read_json_file(AUTH_FILE)
    return str(telegram_id) in auth_data.get('allowed_users', [])


def add_allowed_telegram_id(telegram_id):
    """Add a Telegram ID to the allowed list"""
    auth_data = read_json_file(AUTH_FILE)
    
    if 'allowed_users' not in auth_data:
        auth_data['allowed_users'] = []
    
    if str(telegram_id) not in auth_data['allowed_users']:
        auth_data['allowed_users'].append(str(telegram_id))
        return write_json_file(AUTH_FILE, auth_data)
    
    return True


def remove_allowed_telegram_id(telegram_id):
    """Remove a Telegram ID from the allowed list"""
    auth_data = read_json_file(AUTH_FILE)
    
    if 'allowed_users' in auth_data and str(telegram_id) in auth_data['allowed_users']:
        auth_data['allowed_users'].remove(str(telegram_id))
        return write_json_file(AUTH_FILE, auth_data)
    
    return False


def create_session(telegram_id, user_data=None):
    """Create a new session for a user"""
    sessions = read_json_file(SESSION_FILE)
    session_token = secrets.token_hex(32)
    
    # Clean expired sessions first
    clean_expired_sessions()
    
    # Create new session
    sessions[session_token] = {
        'telegram_id': str(telegram_id),
        'created_at': datetime.now().isoformat(),
        'expires_at': (datetime.now() + timedelta(hours=SESSION_EXPIRY_HOURS)).isoformat(),
        'user_data': user_data or {}
    }
    
    write_json_file(SESSION_FILE, sessions)
    return session_token


def get_session(session_token):
    """Get a session by token"""
    sessions = read_json_file(SESSION_FILE)
    
    if session_token not in sessions:
        return None
    
    session = sessions[session_token]
    
    # Check if session has expired
    if datetime.now() > datetime.fromisoformat(session['expires_at']):
        delete_session(session_token)
        return None
    
    return session


def delete_session(session_token):
    """Delete a session"""
    sessions = read_json_file(SESSION_FILE)
    
    if session_token in sessions:
        del sessions[session_token]
        write_json_file(SESSION_FILE, sessions)
        return True
    
    return False


def clean_expired_sessions():
    """Remove all expired sessions"""
    sessions = read_json_file(SESSION_FILE)
    current_time = datetime.now()
    
    # Filter out expired sessions
    expired_tokens = [
        token for token, session in sessions.items()
        if current_time > datetime.fromisoformat(session['expires_at'])
    ]
    
    # Remove expired sessions
    for token in expired_tokens:
        del sessions[token]
    
    # Save updated sessions
    if expired_tokens:
        write_json_file(SESSION_FILE, sessions)


def create_auth_token(telegram_id):
    """Create a one-time authentication token for a Telegram user"""
    auth_data = read_json_file(AUTH_FILE)
    
    if 'auth_tokens' not in auth_data:
        auth_data['auth_tokens'] = {}
    
    # Generate token
    token = secrets.token_hex(16)
    
    # Store token with expiration time (10 minutes)
    auth_data['auth_tokens'][str(telegram_id)] = {
        'token': token,
        'expires_at': (datetime.now() + timedelta(minutes=10)).isoformat()
    }
    
    write_json_file(AUTH_FILE, auth_data)
    return token


def verify_auth_token(telegram_id, token):
    """Verify a one-time authentication token"""
    auth_data = read_json_file(AUTH_FILE)
    
    if 'auth_tokens' not in auth_data or str(telegram_id) not in auth_data['auth_tokens']:
        return False
    
    token_data = auth_data['auth_tokens'][str(telegram_id)]
    
    # Check if token has expired
    if datetime.now() > datetime.fromisoformat(token_data['expires_at']):
        return False
    
    # Verify token
    if token_data['token'] != token:
        return False
    
    # Token used, remove it
    del auth_data['auth_tokens'][str(telegram_id)]
    write_json_file(AUTH_FILE, auth_data)
    
    return True


def generate_access_code(telegram_id, expiration_hours=24):
    """
    Generate a unique access code for a Telegram ID
    
    This creates a 6-character alphanumeric code that can be used for login
    This code is stored in the auth.json file and expires after a set time
    """
    auth_data = read_json_file(AUTH_FILE)
    
    if 'access_codes' not in auth_data:
        auth_data['access_codes'] = {}
    
    # Clean expired codes
    current_time = datetime.now()
    expired_codes = []
    
    for code, code_data in auth_data['access_codes'].items():
        if current_time > datetime.fromisoformat(code_data['expires_at']):
            expired_codes.append(code)
    
    for code in expired_codes:
        del auth_data['access_codes'][code]
    
    # Generate a short 6-character alphanumeric code
    code = ''.join(secrets.choice('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ') for _ in range(6))
    
    # Store the code
    auth_data['access_codes'][code] = {
        'telegram_id': str(telegram_id),
        'created_at': current_time.isoformat(),
        'expires_at': (current_time + timedelta(hours=expiration_hours)).isoformat()
    }
    
    write_json_file(AUTH_FILE, auth_data)
    return code


def verify_access_code(telegram_id, code):
    """
    Verify if an access code is valid for the given Telegram ID
    
    Returns True if the code is valid and not expired, False otherwise
    """
    auth_data = read_json_file(AUTH_FILE)
    
    if 'access_codes' not in auth_data or code not in auth_data['access_codes']:
        return False
    
    code_data = auth_data['access_codes'][code]
    
    # Check if code is for this Telegram ID
    if code_data['telegram_id'] != str(telegram_id):
        return False
    
    # Check if code has expired
    if datetime.now() > datetime.fromisoformat(code_data['expires_at']):
        # Remove expired code
        del auth_data['access_codes'][code]
        write_json_file(AUTH_FILE, auth_data)
        return False
    
    # Code is valid, remove it (one-time use)
    del auth_data['access_codes'][code]
    write_json_file(AUTH_FILE, auth_data)
    
    return True


def list_active_access_codes():
    """
    List all active access codes
    
    Returns a dictionary with code -> user info mapping
    Removes expired codes in the process
    """
    auth_data = read_json_file(AUTH_FILE)
    
    if 'access_codes' not in auth_data:
        return {}
    
    # Clean expired codes
    current_time = datetime.now()
    expired_codes = []
    active_codes = {}
    
    for code, code_data in auth_data['access_codes'].items():
        if current_time > datetime.fromisoformat(code_data['expires_at']):
            expired_codes.append(code)
        else:
            # Get user info for this code
            user_id = code_data['telegram_id']
            user = get_user(user_id)
            
            if user:
                active_codes[code] = {
                    'telegram_id': user_id,
                    'username': user.get('username', 'Unknown'),
                    'name': f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                    'expires_at': code_data['expires_at']
                }
            else:
                active_codes[code] = {
                    'telegram_id': user_id,
                    'username': 'Unknown',
                    'name': 'Unknown User',
                    'expires_at': code_data['expires_at']
                }
    
    # Remove expired codes
    if expired_codes:
        for code in expired_codes:
            del auth_data['access_codes'][code]
        
        write_json_file(AUTH_FILE, auth_data)
    
    return active_codes