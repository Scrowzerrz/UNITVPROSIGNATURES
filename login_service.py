import logging
from datetime import datetime

from config import LOGINS_FILE, PLANS
from db_utils import read_json_file, write_json_file

# Configuração de logging
logger = logging.getLogger(__name__)

def add_login(plan_type, login_data):
    """
    Adiciona um novo login à lista de logins disponíveis.
    
    Args:
        plan_type (str): Tipo de plano ('30_days', '6_months', '1_year')
        login_data (dict): Dados do login (username, password, etc.)
    
    Returns:
        bool: True se o login foi adicionado com sucesso, False caso contrário
    """
    # Validar tipo de plano
    if plan_type not in PLANS:
        logger.error(f"Tipo de plano inválido: {plan_type}")
        return False
    
    # Garantir que login_data tem os campos necessários
    if 'username' not in login_data or 'password' not in login_data:
        logger.error("Dados de login incompletos")
        return False
    
    # Adicionar timestamp
    login_data['added_at'] = datetime.now().isoformat()
    
    # Obter logins existentes
    logins = read_json_file(LOGINS_FILE)
    
    # Adicionar o novo login
    logins[plan_type].append(login_data)
    
    # Salvar logins atualizados
    return write_json_file(LOGINS_FILE, logins)


def add_login_batch(plan_type, login_list):
    """
    Adiciona múltiplos logins de uma vez.
    
    Args:
        plan_type (str): Tipo de plano ('30_days', '6_months', '1_year')
        login_list (list): Lista de dicionários com dados de login
    
    Returns:
        tuple: (bool, int) - Sucesso da operação e número de logins adicionados
    """
    # Validar tipo de plano
    if plan_type not in PLANS:
        logger.error(f"Tipo de plano inválido: {plan_type}")
        return False, 0
    
    # Obter logins existentes
    logins = read_json_file(LOGINS_FILE)
    added_count = 0
    
    # Adicionar cada login da lista
    for login_data in login_list:
        # Validar dados
        if 'username' not in login_data or 'password' not in login_data:
            logger.warning("Dados de login incompletos, ignorando")
            continue
        
        # Adicionar timestamp
        login_data['added_at'] = datetime.now().isoformat()
        
        # Adicionar o login
        logins[plan_type].append(login_data)
        added_count += 1
    
    # Salvar logins atualizados
    success = write_json_file(LOGINS_FILE, logins)
    
    return success, added_count


def get_available_login(plan_type):
    """
    Obtém um login disponível para o tipo de plano especificado.
    
    Args:
        plan_type (str): Tipo de plano ('30_days', '6_months', '1_year')
    
    Returns:
        dict: Dados do login ou None se não houver logins disponíveis
    """
    # Validar tipo de plano
    if plan_type not in PLANS:
        logger.error(f"Tipo de plano inválido: {plan_type}")
        return None
    
    # Obter logins
    logins = read_json_file(LOGINS_FILE)
    
    # Verificar se há logins disponíveis para o plano
    if not logins.get(plan_type) or len(logins[plan_type]) == 0:
        logger.warning(f"Nenhum login disponível para o plano {plan_type}")
        return None
    
    # Retornar o primeiro login disponível (sem removê-lo ainda)
    return logins[plan_type][0]


def remove_login(plan_type, login_data):
    """
    Remove um login da lista de logins disponíveis.
    
    Args:
        plan_type (str): Tipo de plano ('30_days', '6_months', '1_year')
        login_data (dict): Dados do login a ser removido
    
    Returns:
        bool: True se o login foi removido com sucesso, False caso contrário
    """
    # Validar tipo de plano
    if plan_type not in PLANS:
        logger.error(f"Tipo de plano inválido: {plan_type}")
        return False
    
    # Obter logins
    logins = read_json_file(LOGINS_FILE)
    
    # Verificar se há logins para o plano
    if not logins.get(plan_type) or len(logins[plan_type]) == 0:
        logger.warning(f"Nenhum login disponível para o plano {plan_type}")
        return False
    
    # Encontrar o login a ser removido
    for i, login in enumerate(logins[plan_type]):
        if login.get('username') == login_data.get('username'):
            # Remover o login
            logins[plan_type].pop(i)
            
            # Salvar logins atualizados
            return write_json_file(LOGINS_FILE, logins)
    
    logger.warning(f"Login {login_data.get('username')} não encontrado para o plano {plan_type}")
    return False


def count_available_logins():
    """
    Conta o número de logins disponíveis para cada tipo de plano.
    
    Returns:
        dict: Dicionário com tipos de plano como chaves e contagens como valores
    """
    logins = read_json_file(LOGINS_FILE)
    counts = {}
    
    for plan_type in PLANS.keys():
        counts[plan_type] = len(logins.get(plan_type, []))
    
    return counts