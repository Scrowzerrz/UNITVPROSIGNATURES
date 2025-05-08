#!/usr/bin/env python3
import json
import logging
from datetime import datetime
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
PAYMENTS_FILE = 'data/payments.json'
USERS_FILE = 'data/users.json'
LOGINS_FILE = 'data/logins.json'

# Functions
def read_json_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Error loading {file_path}: {e}")
        return {}

def write_json_file(file_path, data):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error writing to {file_path}: {e}")
        return False

def fix_inconsistent_payments():
    """
    Identifica e corrige pagamentos inconsistentes no sistema.
    - Marca pagamentos fantasma como entregues
    - Inicializa a estrutura de planos para usuários que não a possuem
    """
    payments = read_json_file(PAYMENTS_FILE)
    users = read_json_file(USERS_FILE)
    
    # Contador de correções
    fixed_count = 0
    
    # 1. Identificar pagamentos aprovados mas não entregues
    for payment_id, payment in payments.items():
        if payment.get('status') == 'approved' and not payment.get('login_delivered', False):
            user_id = payment.get('user_id')
            plan_type = payment.get('plan_type')
            
            if not user_id or not plan_type:
                logger.warning(f"Pagamento ID {payment_id} com dados incompletos - ignorando")
                continue
                
            user = users.get(str(user_id))
            if not user:
                logger.warning(f"Usuário ID {user_id} não encontrado para pagamento ID {payment_id}")
                continue
            
            # 2. Verificar se o usuário tem a estrutura de planos
            if 'plans' not in user:
                logger.info(f"Inicializando estrutura de planos para usuário ID {user_id}")
                user['plans'] = []
            
            # 3. Verificar se o usuário já tem plano do mesmo tipo (possivelmente já entregue)
            already_has_plan = False
            for plan in user.get('plans', []):
                if plan.get('plan_type') == plan_type and plan.get('active', False):
                    already_has_plan = True
                    break
            
            # 4. Para pagamentos aprovados sem login entregue, verificar outras pistas
            if already_has_plan:
                # O usuário já tem um plano do mesmo tipo - marcar este pagamento como entregue
                logger.info(f"Marcando pagamento ID {payment_id} como entregue (usuário já tem plano do tipo {plan_type})")
                payment['login_delivered'] = True
                fixed_count += 1
            elif user.get('login_info') is not None:
                # O usuário tem informações de login no formato antigo - migrar
                logger.info(f"Migrando plano antigo para o novo sistema para usuário ID {user_id}")
                
                # Criar um plano com as informações antigas
                plan_id = str(uuid.uuid4())
                
                # Usar informações existentes se disponíveis, ou criar um plano básico
                if user.get('plan_type') == plan_type and user.get('has_active_plan', False):
                    new_plan = {
                        'id': plan_id,
                        'plan_type': user.get('plan_type'),
                        'created_at': datetime.now().isoformat(),
                        'expiration_date': user.get('plan_expiration'),
                        'login_info': user.get('login_info'),
                        'payment_id': payment_id,
                        'expiration_notified': False,
                        'active': True
                    }
                    
                    user['plans'].append(new_plan)
                    payment['login_delivered'] = True
                    payment['plan_id'] = plan_id
                    fixed_count += 1
            else:
                # Nenhum plano existe e é um pagamento aprovado sem login entregue
                # Solução: marcar o pagamento como entregue (plano fantasma)
                logger.info(f"Marcando pagamento ID {payment_id} como entregue (plano fantasma)")
                payment['login_delivered'] = True
                payment['is_ghost_payment'] = True
                fixed_count += 1
            
    # 5. Salvar as alterações
    logger.info(f"Corrigido(s) {fixed_count} pagamento(s) inconsistente(s)")
    write_json_file(PAYMENTS_FILE, payments)
    write_json_file(USERS_FILE, users)
    
    return fixed_count

if __name__ == "__main__":
    fixed = fix_inconsistent_payments()
    print(f"Processo concluído. {fixed} problemas corrigidos.")