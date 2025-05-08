import uuid
import time
import logging
import requests
from datetime import datetime, timedelta

from config import PAYMENTS_FILE, PLANS, BOT_CONFIG_FILE
from db_utils import read_json_file, write_json_file
from user_service import get_user, save_user, assign_plan_to_user

# Configuração de logging
logger = logging.getLogger(__name__)

def create_payment(user_id, plan_type, amount, coupon_code=None):
    """
    Cria um novo pagamento.
    
    Args:
        user_id (str): ID do usuário no Telegram
        plan_type (str): Tipo de plano ('30_days', '6_months', '1_year')
        amount (float): Valor do pagamento
        coupon_code (str, optional): Código do cupom aplicado
    
    Returns:
        str: ID do pagamento criado
    """
    # Gerar ID único para o pagamento
    payment_id = str(uuid.uuid4())
    
    # Registrar o pagamento
    payments = read_json_file(PAYMENTS_FILE)
    
    # Criar dados do pagamento
    payment_data = {
        'id': payment_id,
        'user_id': str(user_id),
        'plan_type': plan_type,
        'amount': amount,
        'status': 'pending',
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
        'timestamp': int(time.time()),  # Adiciona timestamp para facilitar cálculos de expiração
        'payment_method': None,
        'payer_name': None,
        'pix_code': None,
        'pix_image': None,
        'mp_payment_id': None,
        'login_delivered': False
    }
    
    if coupon_code:
        payment_data['coupon_code'] = coupon_code
    
    # Salvar o pagamento
    payments[payment_id] = payment_data
    write_json_file(PAYMENTS_FILE, payments)
    
    return payment_id


def get_payment(payment_id):
    """Retorna um pagamento pelo ID"""
    return read_json_file(PAYMENTS_FILE).get(payment_id)


def update_payment(payment_id, data):
    """Atualiza os dados de um pagamento"""
    payments = read_json_file(PAYMENTS_FILE)
    
    if payment_id in payments:
        # Atualizar o campo updated_at
        data['updated_at'] = datetime.now().isoformat()
        
        # Atualizar os dados do pagamento
        payments[payment_id].update(data)
        
        # Salvar os dados atualizados
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
    current_time = time.time()
    
    for payment_id, payment in payments.items():
        # Verificar se o pagamento é deste usuário e está pendente
        if (payment['user_id'] == str(user_id) and 
            payment['status'] == 'pending'):
            
            # Verificar se o pagamento expirou (10 minutos)
            if current_time - payment.get('timestamp', 0) > 600:  # 600 segundos = 10 minutos
                logger.info(f"Pagamento {payment_id} expirou automaticamente após 10 minutos")
                cancel_payment(payment_id)
                continue
            
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
        
        if not mp_payment_id:
            logger.error("Tentativa de cancelar pagamento sem ID do Mercado Pago")
            return False
        
        # Obter configurações do Mercado Pago
        bot_config = read_json_file(BOT_CONFIG_FILE)
        payment_settings = bot_config.get('payment_settings', {})
        mercado_pago_settings = payment_settings.get('mercado_pago', {})
        access_token = mercado_pago_settings.get('access_token')
        
        if not access_token:
            logger.error("Access token do Mercado Pago não configurado")
            return False
        
        # Fazer requisição para cancelar o pagamento
        url = f"https://api.mercadopago.com/v1/payments/{mp_payment_id}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        data = {
            "status": "cancelled"
        }
        
        response = requests.put(url, json=data, headers=headers)
        
        if response.status_code == 200:
            logger.info(f"Pagamento {mp_payment_id} cancelado no Mercado Pago com sucesso")
            return True
        else:
            logger.error(f"Erro ao cancelar pagamento {mp_payment_id} no Mercado Pago: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Erro ao cancelar pagamento no Mercado Pago: {str(e)}")
        return False


def cancel_payment(payment_id):
    """
    Cancela um pagamento e limpa recursos associados (como QR codes do Mercado Pago)
    
    Args:
        payment_id (str): ID do pagamento a ser cancelado
        
    Returns:
        bool: True se o cancelamento foi bem-sucedido, False caso contrário
    """
    payment = get_payment(payment_id)
    
    if not payment:
        logger.error(f"Pagamento {payment_id} não encontrado ao tentar cancelar")
        return False
    
    # Verificar se o pagamento já está em um estado final
    if payment['status'] in ['completed', 'cancelled', 'rejected']:
        logger.info(f"Pagamento {payment_id} já está em estado final: {payment['status']}")
        return False
    
    # Se o pagamento foi feito pelo Mercado Pago, cancelar no Mercado Pago
    if payment.get('payment_method') == 'pix_mercado_pago' and payment.get('mp_payment_id'):
        _cancel_mercado_pago_payment(payment['mp_payment_id'])
    
    # Atualizar o status do pagamento para cancelado
    update_payment(payment_id, {
        'status': 'cancelled',
        'cancelled_at': datetime.now().isoformat()
    })
    
    return True


def assign_login_to_user(user_id, plan_type, payment_id):
    """
    Atribui um login disponível ao usuário após o pagamento.
    
    Args:
        user_id (str): ID do usuário no Telegram
        plan_type (str): Tipo de plano adquirido
        payment_id (str): ID do pagamento
    
    Returns:
        tuple: (bool, str) - Sucesso da operação e mensagem/informações do login
    """
    from login_service import get_available_login
    
    # Obter login disponível
    login_data = get_available_login(plan_type)
    
    if not login_data:
        logger.error(f"Nenhum login disponível para o plano {plan_type}")
        return False, "Nenhum login disponível para este plano. Entre em contato com o suporte."
    
    # Atribuir plano ao usuário
    user = get_user(user_id)
    
    if not user:
        logger.error(f"Usuário {user_id} não encontrado ao atribuir login")
        return False, "Erro ao encontrar usuário. Entre em contato com o suporte."
    
    # Calcular duração do plano
    duration_days = PLANS[plan_type]['duration_days']
    
    # Atualizar dados do usuário
    user['has_active_plan'] = True
    user['plan_type'] = plan_type
    user['plan_expiration'] = (datetime.now() + timedelta(days=duration_days)).isoformat()
    user['login_info'] = login_data
    user['is_first_buy'] = False
    
    # Salvar usuário
    if not save_user(user_id, user):
        logger.error(f"Erro ao salvar dados do usuário {user_id}")
        return False, "Erro ao atualizar dados do usuário. Entre em contato com o suporte."
    
    # Atualizar dados do pagamento
    update_payment(payment_id, {
        'login_delivered': True,
        'login_data': login_data
    })
    
    # Remover o login da lista de disponíveis
    from login_service import remove_login
    remove_login(plan_type, login_data)
    
    # Check if user was referred by someone
    if user.get('referred_by'):
        try:
            # Process successful referral
            from user_service import process_successful_referral
            process_successful_referral(user['referred_by'])
        except Exception as e:
            logger.error(f"Erro ao processar indicação bem-sucedida: {str(e)}")
    
    # Retornar informações do login
    login_info = (
        f"📱 *Dados de Acesso* 📱\n\n"
        f"Usuário: `{login_data['username']}`\n"
        f"Senha: `{login_data['password']}`"
    )
    
    if 'expiration_date' in login_data:
        login_info += f"\nValidade: {login_data['expiration_date']}"
    
    if 'notes' in login_data:
        login_info += f"\n\nObservações: {login_data['notes']}"
    
    return True, login_info


def check_should_suspend_sales():
    """
    Verifica se as vendas devem ser suspensas com base na disponibilidade de logins.
    
    Returns:
        bool: True se as vendas devem ser suspensas, False caso contrário
    """
    from login_service import count_available_logins
    from config import MINIMUM_LOGINS_THRESHOLD
    
    # Verificar se há um limite mínimo configurado
    if MINIMUM_LOGINS_THRESHOLD <= 0:
        return False
    
    # Contar logins disponíveis
    total_available = sum(count_available_logins().values())
    
    # Suspender vendas se estiver abaixo do limite
    return total_available < MINIMUM_LOGINS_THRESHOLD


def suspend_sales():
    """
    Suspende as vendas do bot.
    
    Returns:
        bool: True se a operação foi bem-sucedida, False caso contrário
    """
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    # Atualizar configuração
    bot_config['sales_enabled'] = False
    
    # Salvar configuração
    return write_json_file(BOT_CONFIG_FILE, bot_config)


def resume_sales():
    """
    Retoma as vendas do bot.
    
    Returns:
        bool: True se a operação foi bem-sucedida, False caso contrário
    """
    bot_config = read_json_file(BOT_CONFIG_FILE)
    
    # Atualizar configuração
    bot_config['sales_enabled'] = True
    
    # Salvar configuração
    return write_json_file(BOT_CONFIG_FILE, bot_config)


def sales_enabled():
    """
    Verifica se as vendas estão habilitadas.
    
    Returns:
        bool: True se as vendas estão habilitadas, False caso contrário
    """
    bot_config = read_json_file(BOT_CONFIG_FILE)
    return bot_config.get('sales_enabled', True)


def get_pending_approvals():
    """
    Retorna pagamentos pendentes de aprovação manual.
    
    Returns:
        list: Lista de pagamentos pendentes de aprovação
    """
    payments = read_json_file(PAYMENTS_FILE)
    pending_approvals = []
    
    for payment_id, payment in payments.items():
        if payment['status'] == 'pending_approval':
            pending_approvals.append(payment)
    
    return pending_approvals


def get_users_waiting_for_login():
    """
    Retorna usuários que pagaram mas ainda não receberam login.
    
    Returns:
        list: Lista de pagamentos de usuários aguardando login
    """
    from config import PLANS
    
    payments = read_json_file(PAYMENTS_FILE)
    if not isinstance(payments, dict):
        logger.error(f"Payments file returned non-dict type: {type(payments)}")
        return []
        
    waiting_users = []
    
    for payment_id, payment in payments.items():
        if (isinstance(payment, dict) and
            payment.get('status') == 'completed' and 
            not payment.get('login_delivered', False) and 
            payment.get('plan_type') in PLANS):
            
            # Adicionar o ID do pagamento ao dicionário para referência
            payment_with_id = payment.copy()
            payment_with_id['payment_id'] = payment_id
            waiting_users.append(payment_with_id)
    
    return waiting_users


def format_currency(value):
    """
    Formata um valor numérico como moeda (BRL).
    
    Args:
        value (float): Valor a ser formatado
    
    Returns:
        str: Valor formatado
    """
    return f"R$ {value:.2f}".replace('.', ',')


def calculate_plan_price(user_id, plan_type):
    """
    Calcula o preço de um plano considerando descontos sazonais.
    
    Args:
        user_id (str): ID do usuário no Telegram
        plan_type (str): Tipo de plano
    
    Returns:
        float: Preço do plano com descontos aplicáveis
    """
    # Obter preço base do plano
    if plan_type not in PLANS:
        logger.error(f"Tipo de plano inválido: {plan_type}")
        return 0
    
    base_price = PLANS[plan_type]['price']
    
    # Verificar se há descontos sazonais aplicáveis
    bot_config = read_json_file(BOT_CONFIG_FILE)
    seasonal_discounts = bot_config.get('seasonal_discounts', {})
    current_time = datetime.now()
    applicable_discount = 0
    
    for discount_id, discount in seasonal_discounts.items():
        # Verificar se o desconto ainda está válido
        if 'expires_at' in discount:
            try:
                expiration_date = datetime.fromisoformat(discount['expires_at'])
                if current_time > expiration_date:
                    # Desconto expirado, pular
                    continue
            except (ValueError, TypeError) as e:
                logger.error(f"Erro ao processar data de expiração do desconto {discount_id}: {e}")
                continue

        # Verificar se o desconto se aplica a este plano
        applicable_plans = discount.get('applicable_plans')
        
        if (applicable_plans is None or plan_type in applicable_plans):
            # Aplicar o maior desconto encontrado
            discount_percent = discount.get('discount_percent', 0)
            if discount_percent > applicable_discount:
                applicable_discount = discount_percent
    
    # Aplicar desconto sazonal se houver
    if applicable_discount > 0:
        discount_amount = base_price * (applicable_discount / 100)
        final_price = base_price - discount_amount
    else:
        final_price = base_price
    
    return final_price