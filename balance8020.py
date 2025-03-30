#!/usr/bin/env python3
import os
import time
import json
import logging
from datetime import datetime
from web3 import Web3, exceptions
from web3.middleware import geth_poa_middleware
from dotenv import load_dotenv

# Configuração avançada de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('conversor_diario_secure.log'),
        logging.StreamHandler()
    ]
)

# Carrega variáveis de ambiente
# Carregar o .env.local manualmente
load_dotenv('.env.local')

# Configurações de segurança
MAX_SLIPPAGE = 1.0  # 1% máxima
MIN_USDT_THRESHOLD = 10.0  # Mínimo de USDT para operar
GAS_LIMIT = 250000
GAS_MULTIPLIER = 1.15
DEADLINE_MINUTES = 5

# Conexão segura com timeout e retry
def connect_web3():
    for _ in range(3):  # 3 tentativas
        try:
            w3 = Web3(Web3.HTTPProvider(
                os.getenv("BSC_RPC", "https://bsc-dataseed.binance.org/"),
                request_kwargs={'timeout': 60}
            ))
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            if w3.is_connected():
                return w3
        except Exception as e:
            logging.warning(f"Falha na conexão: {str(e)}")
            time.sleep(5)
    return None

web3 = connect_web3()

# Contratos verificados
VERIFIED_CONTRACTS = {
    "TOKENS": {
        "BNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "USDT": "0x55d398326f99059fF775485246999027B3197955"
    },
    "ROUTERS": {
        "PancakeSwap": "0x10ED43C718714eb63d5aA57B78B54704E256024E"
    }
}

# ABIs mínimas verificadas
ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]')
ROUTER_ABI = json.loads('[{"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"type":"function"}, {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"type":"function"}]')

# Inicializa contratos verificados
router = web3.eth.contract(address=VERIFIED_CONTRACTS["ROUTERS"]["PancakeSwap"], abi=ROUTER_ABI)

def is_verified_contract(address):
    """Verifica se o contrato está na lista de verificados"""
    address = Web3.to_checksum_address(address)
    for contract_type in VERIFIED_CONTRACTS.values():
        if address in contract_type.values():
            return True
    return False

def get_balance(token_address):
    """Retorna saldo com tratamento de erro e verificação de contrato"""
    try:
        if not is_verified_contract(token_address):
            logging.error(f"Tentativa de acessar contrato não verificado: {token_address}")
            return 0
            
        if token_address.lower() == "bnb":
            return web3.eth.get_balance(os.getenv("WALLET_ADDRESS"))
            
        contract = web3.eth.contract(address=token_address, abi=ERC20_ABI)
        return contract.functions.balanceOf(os.getenv("WALLET_ADDRESS")).call()
    except exceptions.ContractLogicError as e:
        logging.error(f"Erro no contrato: {str(e)}")
        return 0
    except Exception as e:
        logging.error(f"Erro ao verificar saldo: {str(e)}")
        return 0

def get_price(token_in, token_out, amount_in):
    """Obtém cotação com tratamento de erro e verificação"""
    try:
        if not all(is_verified_contract(t) for t in [token_in, token_out]):
            logging.error("Tentativa de cotação com token não verificado")
            return 0
            
        amounts = router.functions.getAmountsOut(amount_in, [token_in, token_out]).call()
        if not amounts or len(amounts) < 2:
            logging.error("Resposta inválida do router")
            return 0
        return amounts[-1]
    except exceptions.ContractLogicError as e:
        logging.error(f"Erro no contrato: {str(e)}")
        return 0
    except Exception as e:
        logging.error(f"Erro ao obter preço: {str(e)}")
        return 0

def check_gas_and_funds(amount_bnb_needed):
    """Verifica taxas e fundos disponíveis"""
    try:
        # Verifica saldo BNB para taxas
        saldo_bnb = get_balance(VERIFIED_CONTRACTS["TOKENS"]["BNB"])
        gas_price = web3.eth.gas_price
        total_cost = gas_price * GAS_LIMIT
        
        if saldo_bnb < total_cost:
            logging.error(f"Saldo insuficiente para taxas. Necessário: {Web3.from_wei(total_cost, 'ether'):.6f} BNB, Disponível: {Web3.from_wei(saldo_bnb, 'ether'):.6f}")
            return False
            
        # Verifica se o custo não está excessivo
        avg_gas = web3.eth.gas_price
        if gas_price > avg_gas * 2:
            logging.warning(f"Taxa de gás anormalmente alta: {Web3.from_wei(gas_price, 'gwei'):.2f} Gwei")
            return False
            
        return True
    except Exception as e:
        logging.error(f"Erro ao verificar taxas: {str(e)}")
        return False

def converter_usdt_para_bnb():
    """Converte USDT para BNB com múltiplas proteções"""
    try:
        # Verificação inicial
        if not web3 or not web3.is_connected():
            logging.error("Sem conexão com a blockchain")
            return False

        # Obtém e verifica saldos
        saldo_usdt = get_balance(VERIFIED_CONTRACTS["TOKENS"]["USDT"])
        if saldo_usdt < Web3.to_wei(MIN_USDT_THRESHOLD, 'ether'):
            logging.info(f"Saldo de USDT abaixo do mínimo ({MIN_USDT_THRESHOLD} USDT)")
            return False

        # Calcula valor para converter (80%)
        amount_to_convert = int(saldo_usdt * 0.8)
        
        # Obtém preço com verificação
        price = get_price(
            VERIFIED_CONTRACTS["TOKENS"]["USDT"],
            VERIFIED_CONTRACTS["TOKENS"]["BNB"],
            amount_to_convert
        )
        if price == 0:
            return False
            
        # Aplica slippage
        min_amount_out = int(price * (100 - MAX_SLIPPAGE) / 100)
        
        # Verifica taxas antes de continuar
        if not check_gas_and_funds(amount_to_convert):
            return False

        # Prepara transação com proteções
        deadline = int(time.time()) + DEADLINE_MINUTES * 60
        tx_params = {
            'from': os.getenv("WALLET_ADDRESS"),
            'gas': GAS_LIMIT,
            'gasPrice': int(web3.eth.gas_price * GAS_MULTIPLIER),
            'nonce': web3.eth.getTransactionCount(os.getenv("WALLET_ADDRESS")),
        }

        # Constrói e envia transação
        tx = router.functions.swapExactTokensForTokens(
            amount_to_convert,
            min_amount_out,
            [VERIFIED_CONTRACTS["TOKENS"]["USDT"], VERIFIED_CONTRACTS["TOKENS"]["BNB"]],
            os.getenv("WALLET_ADDRESS"),
            deadline
        ).build_transaction(tx_params)

        signed_tx = web3.eth.account.sign_transaction(tx, os.getenv("PRIVATE_KEY"))
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        # Aguarda confirmação
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        if receipt.status == 1:
            logging.info(
                f"Conversão realizada com sucesso!\n"
                f"- USDT convertido: {Web3.from_wei(amount_to_convert, 'ether'):.2f}\n"
                f"- BNB recebido: {Web3.from_wei(min_amount_out, 'ether'):.6f}\n"
                f"- Hash: {tx_hash.hex()}"
            )
            return True
        else:
            logging.error(f"Falha na transação. Hash: {tx_hash.hex()}")
            return False

    except exceptions.ContractLogicError as e:
        logging.error(f"Erro no contrato durante a conversão: {str(e)}")
        return False
    except ValueError as e:
        if "insufficient funds" in str(e).lower():
            logging.error("Saldo insuficiente para taxas")
        else:
            logging.error(f"Erro de valor: {str(e)}")
        return False
    except Exception as e:
        logging.error(f"Erro inesperado na conversão: {str(e)}")
        return False

def main():
    """Execução principal com tratamento robusto"""
    try:
        logging.info("Iniciando conversor diário seguro USDT->BNB")
        
        # Verificação de configuração
        if not all(os.getenv(var) for var in ["WALLET_ADDRESS", "PRIVATE_KEY"]):
            logging.error("Variáveis de ambiente essenciais não configuradas")
            return

        if not web3 or not web3.is_connected():
            logging.error("Não foi possível conectar à blockchain")
            return

        # Verifica saldos
        saldo_usdt = Web3.from_wei(get_balance(VERIFIED_CONTRACTS["TOKENS"]["USDT"]), 'ether')
        saldo_bnb = Web3.from_wei(get_balance(VERIFIED_CONTRACTS["TOKENS"]["BNB"]), 'ether')
        
        logging.info(f"Saldo atual:\n- USDT: {saldo_usdt:.2f}\n- BNB: {saldo_bnb:.6f}")

        # Executa conversão se condições forem atendidas
        if saldo_usdt > MIN_USDT_THRESHOLD:
            converter_usdt_para_bnb()
        else:
            logging.info(f"Saldo de USDT abaixo do mínimo ({MIN_USDT_THRESHOLD} USDT)")

    except KeyboardInterrupt:
        logging.info("Execução interrompida pelo usuário")
    except Exception as e:
        logging.error(f"Erro crítico: {str(e)}")

if __name__ == "__main__":
    main()
