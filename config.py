import os
import json
import secrets
from datetime import datetime

# Bot configuration
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_TELEGRAM_ID', '0'))

# File paths
DATA_DIR = 'data'
USERS_FILE = f'{DATA_DIR}/users.json'
PAYMENTS_FILE = f'{DATA_DIR}/payments.json'
LOGINS_FILE = f'{DATA_DIR}/logins.json'
BOT_CONFIG_FILE = f'{DATA_DIR}/bot_config.json'
AUTH_FILE = f'{DATA_DIR}/auth.json'
SESSION_FILE = f'{DATA_DIR}/sessions.json'

# Session configurations
SESSION_EXPIRY_HOURS = 24

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Plans and pricing
PLANS = {
    '30_days': {
        'name': 'Plano 30 Dias',
        'duration_days': 30,
        'first_buy_price': 9.00,
        'regular_price': 20.00,
        'first_buy_discount': True
    },
    '6_months': {
        'name': 'Plano 6 Meses',
        'duration_days': 180,
        'first_buy_price': 40.00,  # 50 with 20% discount
        'regular_price': 50.00,
        'first_buy_discount': True
    },
    '1_year': {
        'name': 'Plano 1 Ano',
        'duration_days': 365,
        'first_buy_price': 110.00,
        'regular_price': 110.00,
        'first_buy_discount': False
    }
}

# Initialize JSON files if they don't exist
def init_json_files():
    # Create users.json if it doesn't exist
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w') as f:
            json.dump({}, f)
    
    # Create payments.json if it doesn't exist
    if not os.path.exists(PAYMENTS_FILE):
        with open(PAYMENTS_FILE, 'w') as f:
            json.dump({}, f)
    
    # Create logins.json if it doesn't exist
    if not os.path.exists(LOGINS_FILE):
        with open(LOGINS_FILE, 'w') as f:
            json.dump({
                '30_days': [],
                '6_months': [],
                '1_year': []
            }, f)
    
    # Create bot_config.json if it doesn't exist
    if not os.path.exists(BOT_CONFIG_FILE):
        default_config = {
            'sales_enabled': True,
            'warning_sent': False,
            'sales_suspended_time': None,
            'coupons': {},
            'referral_rewards': {
                'referrer_discount': 10,  # 10% discount
                'referred_discount': 5,   # 5% discount for referred user
                'free_month_after_referrals': 3  # Number of successful referrals for free month
            },
            'payment_settings': {
                'pix': {
                    'enabled': True,
                    'key': 'nossaempresa@email.com',
                    'name': 'Empresa UniTV LTDA',
                    'bank': 'Banco UniTV'
                },
                'mercado_pago': {
                    'enabled': False,
                    'access_token': '',
                    'public_key': ''
                }
            }
        }
        with open(BOT_CONFIG_FILE, 'w') as f:
            json.dump(default_config, f, indent=4)
    
    # Create auth.json if it doesn't exist (stores admin Telegram IDs)
    if not os.path.exists(AUTH_FILE):
        auth_config = {
            'admin_telegram_ids': [ADMIN_ID] if ADMIN_ID else [],
            'allowed_telegram_ids': []  # Telegram IDs allowed to access the admin panel
        }
        with open(AUTH_FILE, 'w') as f:
            json.dump(auth_config, f, indent=4)
    
    # Create sessions.json if it doesn't exist (stores active login sessions)
    if not os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, 'w') as f:
            json.dump({}, f)

# Initialize the files
init_json_files()
