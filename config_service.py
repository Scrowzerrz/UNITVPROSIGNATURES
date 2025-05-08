import logging
import os
from datetime import datetime

from config import BOT_CONFIG_FILE
from db_utils import read_json_file, write_json_file

# Configuração de logging
logger = logging.getLogger(__name__)

def get_bot_config():
    """
    Obtém a configuração completa do bot.
    
    Returns:
        dict: Configuração do bot
    """
    return read_json_file(BOT_CONFIG_FILE)


def save_bot_config(config):
    """
    Salva a configuração do bot.
    
    Args:
        config (dict): Configuração do bot
    
    Returns:
        bool: True se a operação foi bem-sucedida, False caso contrário
    """
    return write_json_file(BOT_CONFIG_FILE, config)


def update_bot_config(config_update):
    """
    Atualiza parcialmente a configuração do bot.
    
    Args:
        config_update (dict): Atualizações para a configuração
    
    Returns:
        bool: True se a operação foi bem-sucedida, False caso contrário
    """
    config = get_bot_config()
    
    # Atualizar recursivamente
    def update_dict(target, source):
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                update_dict(target[key], value)
            else:
                target[key] = value
    
    update_dict(config, config_update)
    return save_bot_config(config)


def get_payment_settings():
    """
    Obtém configurações de pagamento.
    
    Returns:
        dict: Configurações de pagamento
    """
    config = get_bot_config()
    return config.get('payment_settings', {})


def save_payment_settings(settings):
    """
    Salva configurações de pagamento.
    
    Args:
        settings (dict): Configurações de pagamento
    
    Returns:
        bool: True se a operação foi bem-sucedida, False caso contrário
    """
    config = get_bot_config()
    config['payment_settings'] = settings
    return save_bot_config(config)


def save_pix_settings(pix_key, pix_recipient_name, pix_recipient_document):
    """
    Salva configurações de PIX.
    
    Args:
        pix_key (str): Chave PIX
        pix_recipient_name (str): Nome do destinatário
        pix_recipient_document (str): CPF/CNPJ do destinatário
    
    Returns:
        bool: True se a operação foi bem-sucedida, False caso contrário
    """
    config = get_bot_config()
    
    if 'payment_settings' not in config:
        config['payment_settings'] = {}
    
    config['payment_settings']['pix'] = {
        'key': pix_key,
        'recipient_name': pix_recipient_name,
        'recipient_document': pix_recipient_document,
        'updated_at': datetime.now().isoformat()
    }
    
    return save_bot_config(config)


def save_mercado_pago_settings(access_token, public_key, enabled=True):
    """
    Salva configurações do Mercado Pago.
    
    Args:
        access_token (str): Token de acesso
        public_key (str): Chave pública
        enabled (bool): Se o Mercado Pago está habilitado
    
    Returns:
        bool: True se a operação foi bem-sucedida, False caso contrário
    """
    config = get_bot_config()
    
    if 'payment_settings' not in config:
        config['payment_settings'] = {}
    
    config['payment_settings']['mercado_pago'] = {
        'access_token': access_token,
        'public_key': public_key,
        'enabled': enabled,
        'updated_at': datetime.now().isoformat()
    }
    
    return save_bot_config(config)


def update_referral_settings(required_referrals, referrer_reward_percent, referred_discount_percent):
    """
    Atualiza configurações do programa de indicação.
    
    Args:
        required_referrals (int): Número de indicações necessárias para recompensa
        referrer_reward_percent (float): Porcentagem de recompensa para quem indica
        referred_discount_percent (float): Porcentagem de desconto para quem é indicado
    
    Returns:
        bool: True se a operação foi bem-sucedida, False caso contrário
    """
    config = get_bot_config()
    
    if 'referral_rewards' not in config:
        config['referral_rewards'] = {}
    
    config['referral_rewards']['free_month_after_referrals'] = required_referrals
    config['referral_rewards']['referrer_discount'] = referrer_reward_percent
    config['referral_rewards']['referred_discount'] = referred_discount_percent
    
    return save_bot_config(config)


def init_json_files():
    """
    Inicializa os arquivos JSON necessários para o funcionamento do bot.
    
    Returns:
        bool: True se todos os arquivos foram inicializados com sucesso, False caso contrário
    """
    from config import (
        USERS_FILE, PAYMENTS_FILE, LOGINS_FILE, BOT_CONFIG_FILE, 
        AUTH_FILE, SESSION_FILE
    )
    
    success = True
    
    # Verifica e cria diretórios necessários
    data_dir = os.path.dirname(USERS_FILE)
    os.makedirs(data_dir, exist_ok=True)
    
    # Inicializar arquivo de configuração do bot
    if not os.path.exists(BOT_CONFIG_FILE):
        default_config = {
            'sales_enabled': True,
            'payment_settings': {
                'pix': {
                    'key': '',
                    'recipient_name': '',
                    'recipient_document': ''
                },
                'mercado_pago': {
                    'access_token': '',
                    'public_key': '',
                    'enabled': False
                }
            },
            'seasonal_discounts': {},
            'coupons': {},
            'referral_rewards': {
                'free_month_after_referrals': 5,
                'referrer_discount': 10,
                'referred_discount': 5
            }
        }
        
        success = success and write_json_file(BOT_CONFIG_FILE, default_config)
    
    # Inicializar arquivo de usuários
    if not os.path.exists(USERS_FILE):
        success = success and write_json_file(USERS_FILE, {})
    
    # Inicializar arquivo de pagamentos
    if not os.path.exists(PAYMENTS_FILE):
        success = success and write_json_file(PAYMENTS_FILE, {})
    
    # Inicializar arquivo de logins
    if not os.path.exists(LOGINS_FILE):
        default_logins = {
            '30_days': [],
            '6_months': [],
            '1_year': []
        }
        success = success and write_json_file(LOGINS_FILE, default_logins)
    
    # Inicializar arquivo de autenticação
    if not os.path.exists(AUTH_FILE):
        default_auth = {
            'allowed_users': [],
            'auth_tokens': {},
            'access_codes': {}
        }
        success = success and write_json_file(AUTH_FILE, default_auth)
    
    # Inicializar arquivo de sessões
    if not os.path.exists(SESSION_FILE):
        success = success and write_json_file(SESSION_FILE, {})
    
    return success