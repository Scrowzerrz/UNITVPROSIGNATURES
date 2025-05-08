import json
import logging
import os

# Configuração de logging
logger = logging.getLogger(__name__)

def read_json_file(file_path):
    """
    Lê um arquivo JSON e retorna seu conteúdo.
    
    Args:
        file_path (str): Caminho para o arquivo JSON
    
    Returns:
        dict: Conteúdo do arquivo JSON ou um dicionário vazio em caso de erro
    """
    try:
        # Verificar se o arquivo existe, se não, criar com um dicionário vazio
        if not os.path.exists(file_path):
            # Garantir que os diretórios existam
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Criar o arquivo com um valor padrão
            with open(file_path, 'w', encoding='utf-8') as f:
                if file_path.endswith('logins.json'):
                    json.dump({
                        '30_days': [],
                        '6_months': [],
                        '1_year': []
                    }, f, indent=4)
                else:
                    json.dump({}, f, indent=4)
            
            # Para logins.json, retornar a estrutura padrão
            if file_path.endswith('logins.json'):
                return {
                    '30_days': [],
                    '6_months': [],
                    '1_year': []
                }
            
            # Para outros arquivos, retornar um dicionário vazio
            return {}
        
        # Ler o arquivo existente
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao ler o arquivo JSON {file_path}: {e}")
        return {}


def write_json_file(file_path, data):
    """
    Escreve dados em um arquivo JSON.
    
    Args:
        file_path (str): Caminho para o arquivo JSON
        data (dict): Dados a serem escritos
    
    Returns:
        bool: True se a operação foi bem-sucedida, False caso contrário
    """
    try:
        # Garantir que os diretórios existam
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Escrever os dados no arquivo
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        
        return True
    except Exception as e:
        logger.error(f"Erro ao escrever no arquivo JSON {file_path}: {e}")
        return False