import uuid
import logging
from datetime import datetime, timedelta

from config import BOT_CONFIG_FILE
from db_utils import read_json_file, write_json_file

# Configuração de logging
logger = logging.getLogger(__name__)

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
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    # Inicializar seção de descontos sazonais se não existir
    if 'seasonal_discounts' not in bot_config:
        bot_config['seasonal_discounts'] = {}
    
    # Validar percentual de desconto
    discount_percent = max(1, min(100, discount_percent))
    
    # Gerar ID para o desconto
    discount_id = str(uuid.uuid4())
    
    # Calcular data de expiração
    expiration_date = (datetime.now() + timedelta(days=expiration_days)).isoformat()
    
    # Criar dados do desconto
    discount_data = {
        'discount_percent': discount_percent,
        'created_at': datetime.now().isoformat(),
        'expires_at': expiration_date,
        'applicable_plans': applicable_plans
    }
    
    # Adicionar o desconto
    bot_config['seasonal_discounts'][discount_id] = discount_data
    
    # Salvar configuração
    write_json_file(BOT_CONFIG_FILE, bot_config)
    
    return discount_id


def remove_seasonal_discount(discount_id):
    """
    Remove um desconto sazonal.
    
    Args:
        discount_id (str): ID do desconto a ser removido
    
    Returns:
        bool: True se o desconto foi removido com sucesso, False caso contrário
    """
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    # Verificar se há descontos sazonais configurados
    if 'seasonal_discounts' not in bot_config:
        logger.warning("Nenhum desconto sazonal configurado")
        return False
    
    # Verificar se o desconto existe
    if discount_id not in bot_config['seasonal_discounts']:
        logger.warning(f"Desconto {discount_id} não encontrado")
        return False
    
    # Remover o desconto
    del bot_config['seasonal_discounts'][discount_id]
    
    # Salvar configuração
    return write_json_file(BOT_CONFIG_FILE, bot_config)


def get_active_seasonal_discounts():
    """
    Retorna todos os descontos sazonais ativos.
    
    Returns:
        dict: Dicionário com os descontos ativos
    """
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    if 'seasonal_discounts' not in bot_config:
        return {}
    
    current_time = datetime.now()
    active_discounts = {}
    
    for discount_id, discount in bot_config['seasonal_discounts'].items():
        # Verificar se o desconto ainda está válido
        if 'expires_at' in discount:
            expiration_date = datetime.fromisoformat(discount['expires_at'])
            if current_time > expiration_date:
                # Desconto expirado, pular
                continue
        
        # Adicionar desconto ativo
        active_discounts[discount_id] = discount
    
    return active_discounts


def add_coupon(code, discount_type, discount_value, expiration_date, max_uses, min_purchase, applicable_plans):
    """
    Adiciona um novo cupom de desconto.
    
    Args:
        code (str): Código do cupom
        discount_type (str): Tipo de desconto ('percent' ou 'fixed')
        discount_value (float): Valor do desconto (porcentagem ou valor fixo)
        expiration_date (str): Data de expiração (ISO format)
        max_uses (int): Número máximo de usos
        min_purchase (float): Valor mínimo de compra
        applicable_plans (list): Lista de planos aos quais o cupom se aplica
    
    Returns:
        bool: True se o cupom foi adicionado com sucesso, False caso contrário
    """
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    # Inicializar seção de cupons se não existir
    if 'coupons' not in bot_config:
        bot_config['coupons'] = {}
    
    # Verificar se o código já existe
    if code in bot_config['coupons']:
        logger.warning(f"Cupom com código {code} já existe")
        return False
    
    # Criar dados do cupom
    coupon_data = {
        'code': code,
        'discount_type': discount_type,
        'discount_value': discount_value,
        'created_at': datetime.now().isoformat(),
        'expires_at': expiration_date,
        'max_uses': max_uses,
        'uses': 0,
        'min_purchase': min_purchase,
        'applicable_plans': applicable_plans
    }
    
    # Adicionar o cupom
    bot_config['coupons'][code] = coupon_data
    
    # Salvar configuração
    return write_json_file(BOT_CONFIG_FILE, bot_config)


def validate_coupon(code, user_id, plan_type, amount):
    """
    Valida um cupom e calcula o desconto.
    
    Args:
        code (str): Código do cupom
        user_id (str): ID do usuário
        plan_type (str): Tipo de plano
        amount (float): Valor original
    
    Returns:
        tuple: (dict, str) - Resultado e mensagem. Se válido, o resultado contém os detalhes do desconto.
    """
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    # Verificar se existem cupons configurados
    if 'coupons' not in bot_config:
        return None, "Nenhum cupom configurado no sistema."
    
    # Verificar se o cupom existe
    if code not in bot_config['coupons']:
        return None, "Cupom não encontrado."
    
    coupon = bot_config['coupons'][code]
    current_time = datetime.now()
    
    # Verificar se o cupom expirou
    if 'expires_at' in coupon:
        expiration_date = datetime.fromisoformat(coupon['expires_at'])
        if current_time > expiration_date:
            return None, "Este cupom expirou."
    
    # Verificar número máximo de usos
    if coupon['uses'] >= coupon['max_uses']:
        return None, "Este cupom atingiu o número máximo de usos."
    
    # Verificar valor mínimo de compra
    if amount < coupon['min_purchase']:
        return None, f"O valor mínimo para este cupom é {coupon['min_purchase']:.2f}."
    
    # Verificar se o plano é aplicável
    if coupon['applicable_plans'] and plan_type not in coupon['applicable_plans']:
        return None, "Este cupom não é válido para este plano."
    
    # Calcular desconto
    if coupon['discount_type'] == 'percent':
        discount = amount * (coupon['discount_value'] / 100)
        discount_text = f"{coupon['discount_value']}%"
    else:  # fixed
        discount = min(coupon['discount_value'], amount)  # Não permite desconto maior que o valor
        discount_text = f"R$ {coupon['discount_value']:.2f}"
    
    final_amount = amount - discount
    
    # Retornar resultado
    return {
        'coupon': coupon,
        'discount': discount,
        'final_amount': final_amount,
        'discount_text': discount_text
    }, "Cupom válido!"


def use_coupon(code, user_id):
    """
    Registra o uso de um cupom.
    
    Args:
        code (str): Código do cupom
        user_id (str): ID do usuário
    
    Returns:
        bool: True se o uso foi registrado com sucesso, False caso contrário
    """
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    # Verificar se o cupom existe
    if 'coupons' not in bot_config or code not in bot_config['coupons']:
        logger.warning(f"Cupom {code} não encontrado ao registrar uso")
        return False
    
    # Incrementar contador de usos
    bot_config['coupons'][code]['uses'] += 1
    
    # Adicionar usuário à lista de usos, se ela existir
    if 'used_by' not in bot_config['coupons'][code]:
        bot_config['coupons'][code]['used_by'] = []
    
    bot_config['coupons'][code]['used_by'].append({
        'user_id': str(user_id),
        'used_at': datetime.now().isoformat()
    })
    
    # Salvar configuração
    return write_json_file(BOT_CONFIG_FILE, bot_config)


def delete_coupon(code):
    """
    Deleta um cupom.
    
    Args:
        code (str): Código do cupom
    
    Returns:
        bool: True se o cupom foi deletado com sucesso, False caso contrário
    """
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    # Verificar se o cupom existe
    if 'coupons' not in bot_config or code not in bot_config['coupons']:
        logger.warning(f"Cupom {code} não encontrado ao deletar")
        return False
    
    # Remover o cupom
    del bot_config['coupons'][code]
    
    # Salvar configuração
    return write_json_file(BOT_CONFIG_FILE, bot_config)