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

# Define constants para módulos de configuração
MINIMUM_LOGINS_THRESHOLD = 5  # Número mínimo de logins que deve estar disponível

# A inicialização dos arquivos JSON agora é feita pelo config_service.py
from config_service import init_json_files

# Initialize the files
init_json_files()
