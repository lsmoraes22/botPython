#!/usr/bin/env python
import os
import time
import json
import logging
import sys
from web3 import Web3
from dotenv import load_dotenv

# Configuração avançada de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('arbitrage.log'),
        logging.StreamHandler()
    ]
)

# Carrega variáveis de ambiente
# Carregar o .env.local manualmente
load_dotenv('.env.local')

# Configurações
BSC_RPC = os.getenv("BSC_RPC", "https://bsc-dataseed.binance.org/")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
MIN_PROFIT_USDT = os.getenv("MIN_PROFIT_USDT", 0.5)  # Lucro mínimo em USDT
TRADE_AMOUNT = os.getenv("TRADE_AMOUNT", 0.1)  # Quantidade de BNB a ser negociada
MAX_SLIPPAGE = os.getenv("MAX_SLIPPAGE", 1.0)  # Slippage máximo em porcentagem
GAS_LIMIT = os.getenv("GAS_LIMIT", 250000)  # Limite de gás padrão
GAS_MULTIPLIER = os.getenv("GAS_MULTIPLIER", 1.15)  # Multiplicador de gás para segurança

# Configuração para redes POA (como BSC)
def poa_middleware(make_request, w3):
    def middleware(method, params):
        if method in ('eth_getBlockByHash', 'eth_getBlockByNumber'):
            response = make_request(method, params)
            if response and 'result' in response and response['result']:
                response['result']['proofOfAuthorityData'] = '0x' + '00' * 32
            return response
        return make_request(method, params)
    return middleware


# Conexão segura com timeout
w3 = Web3(Web3.HTTPProvider(
    BSC_RPC,
    request_kwargs={'timeout': 45}
))

w3.middleware_onion.inject(poa_middleware, layer=0)

# Contratos verificados e confiáveis
VERIFIED_CONTRACTS = {
    "TOKENS": {
        "BNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "USDT": "0x55d398326f99059fF775485246999027B3197955"
    },
    "DEX_ROUTERS": {
        "PancakeSwap": "0x10ED43C718714eb63d5aA57B78B54704E256024E",
        "ApeSwap": "0xcF0feBd3f17CEf5b47b0cD257aCf6025c5BFf3b7"
    }
}

# ABIs mínimas verificadas
ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}, {"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"}, {"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}]')
ROUTER_ABI = json.loads('[{"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"type":"function"}, {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"type":"function"}]')

# Inicializa contratos verificados
router_pancake = w3.eth.contract(address=VERIFIED_CONTRACTS["DEX_ROUTERS"]["PancakeSwap"], abi=ROUTER_ABI)
router_ape = w3.eth.contract(address=VERIFIED_CONTRACTS["DEX_ROUTERS"]["ApeSwap"], abi=ROUTER_ABI)

# Monitor de transações pendentes
pending_transactions = set()

def is_verified_contract(address):
    """Verifica se o contrato está na lista de verificados."""
    address = Web3.to_checksum_address(address)
    for contract_type in VERIFIED_CONTRACTS.values():
        if address in contract_type.values():
            return True
    return False

def is_connected():
    """Verifica conexão com a blockchain."""
    try:
        return w3.is_connected() and w3.eth.get_block('latest')
    except Exception as e:
        logging.error(f"Erro de conexão: {str(e)}")
        return False

def get_balance(token_address):
    """Retorna saldo com tratamento de erro."""
    try:
        if token_address.lower() == "bnb":
            return web3.eth.get_balance(WALLET_ADDRESS)
        
        if not is_verified_contract(token_address):
            logging.warning(f"Tentativa de verificar saldo em contrato não verificado: {token_address}")
            return 0
            
        contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        return contract.functions.balanceOf(WALLET_ADDRESS).call()
    except Exception as e:
        logging.error(f"Erro ao verificar saldo: {str(e)}")
        return 0

def check_allowance(token_address, spender):
    """Verifica allowance com tratamento de erro."""
    try:
        if not is_verified_contract(token_address) or not is_verified_contract(spender):
            logging.warning(f"Tentativa de verificar allowance em contrato não verificado")
            return 0
            
        contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        return contract.functions.allowance(WALLET_ADDRESS, spender).call()
    except Exception as e:
        logging.error(f"Erro ao verificar allowance: {str(e)}")
        return 0

def approve_token(token_address, spender, amount):
    """Aprovação segura apenas do valor necessário."""
    try:
        if not is_verified_contract(token_address) or not is_verified_contract(spender):
            logging.error(f"Tentativa de aprovar token em contrato não verificado")
            return False
            
        current_allowance = check_allowance(token_address, spender)
        if current_allowance >= amount:
            return True
            
        contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        tx = contract.functions.approve(spender, amount).build_transaction({
            'from': WALLET_ADDRESS,
            'gas': GAS_LIMIT,
            'gasPrice': int(w3.eth.gas_price * GAS_MULTIPLIER),
            'nonce': w3.eth.getTransactionCount(WALLET_ADDRESS),
        })
        
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        # Adiciona à lista de transações pendentes
        pending_transactions.add(tx_hash.hex())
        
        # Espera pela confirmação
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        pending_transactions.remove(tx_hash.hex())
        
        if receipt.status == 1:
            logging.info(f"Token aprovado. Hash: {tx_hash.hex()}")
            return True
        else:
            logging.error(f"Falha na aprovação. Hash: {tx_hash.hex()}")
            return False
    except Exception as e:
        if tx_hash.hex() in pending_transactions:
            pending_transactions.remove(tx_hash.hex())
        logging.error(f"Falha na aprovação: {str(e)}")
        return False

def calculate_gas_cost():
    """Calcula custo em BNB e USDT com cache."""
    try:
        gas_price = w3.eth.gas_price
        gas_cost_bnb = gas_price * GAS_LIMIT / 10**18
        
        # Obtém preço BNB/USDT
        amounts = router_pancake.functions.getAmountsOut(
            1 * 10**18, 
            [VERIFIED_CONTRACTS["TOKENS"]["BNB"], VERIFIED_CONTRACTS["TOKENS"]["USDT"]]
        ).call()
        usdt_per_bnb = amounts[1] / 10**18
        
        gas_cost_usdt = gas_cost_bnb * usdt_per_bnb
        return gas_cost_bnb, gas_cost_usdt
    except Exception as e:
        logging.error(f"Erro no cálculo de gás: {str(e)}")
        return 0, 0

def get_price(router_address, token_in, token_out, amount_in):
    """Obtém preço de troca com tratamento de erro."""
    try:
        if not is_verified_contract(router_address) or not is_verified_contract(token_in) or not is_verified_contract(token_out):
            logging.warning(f"Tentativa de obter preço de contrato não verificado")
            return 0
            
        router = w3.eth.contract(address=router_address, abi=ROUTER_ABI)
        amounts = router.functions.getAmountsOut(
            amount_in,
            [token_in, token_out]
        ).call()
        return amounts[-1] if amounts else 0
    except Exception as e:
        logging.error(f"Erro ao obter preço: {str(e)}")
        return 0

def execute_swap(router, token_in, token_out, amount_in, min_profit):
    """Execução segura de swap com verificações."""
    try:
        # Verifica se todos os contratos são verificados
        if not all(is_verified_contract(addr) for addr in [router.address, token_in, token_out]):
            logging.error("Tentativa de swap com contrato não verificado")
            return False

        # Verifica saldo
        balance = get_balance(token_in)
        if balance < amount_in:
            logging.error(f"Saldo insuficiente. Necessário: {amount_in/10**18:.4f}, Disponível: {balance/10**18:.4f}")
            return False

        # Obtém preço com proteção contra front-running
        amounts = router.functions.getAmountsOut(amount_in, [token_in, token_out]).call()
        if not amounts or len(amounts) < 2:
            logging.error("Erro ao obter preço")
            return False
            
        amount_out_min = int(amounts[-1] * (100 - MAX_SLIPPAGE) / 100)
        
        # Verifica lucro considerando slippage
        gas_cost_bnb, gas_cost_usdt = calculate_gas_cost()
        required_profit = max(MIN_PROFIT_USDT, gas_cost_usdt * 3)  # Margem maior para segurança
        
        potential_profit = (amount_out_min - amount_in) / 10**18
        if potential_profit < required_profit:
            logging.info(f"Lucro insuficiente após slippage: {potential_profit:.4f} USDT (Necessário: {required_profit:.4f})")
            return False

        # Aprovação apenas do valor necessário
        if not approve_token(token_in, router.address, amount_in):
            return False

        # Executa swap com proteção contra bots
        deadline = int(time.time()) + 180  # 3 minutos de deadline
        
        tx = router.functions.swapExactTokensForTokens(
            amount_in,
            amount_out_min,
            [token_in, token_out],
            WALLET_ADDRESS,
            deadline
        ).build_transaction({
            'from': WALLET_ADDRESS,
            'gas': GAS_LIMIT,
            'gasPrice': int(w3.eth.gas_price * GAS_MULTIPLIER),
            'nonce': w3.eth.getTransactionCount(WALLET_ADDRESS),
        })

        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        # Adiciona à lista de transações pendentes
        pending_transactions.add(tx_hash.hex())
        
        # Espera pela confirmação
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        pending_transactions.remove(tx_hash.hex())
        
        if receipt.status == 1:
            logging.info(f"Swap executado com sucesso! Hash: {tx_hash.hex()}")
            return True
        else:
            logging.error(f"Falha na execução do swap. Hash: {tx_hash.hex()}")
            return False
            
    except Exception as e:
        if 'tx_hash' in locals() and tx_hash.hex() in pending_transactions:
            pending_transactions.remove(tx_hash.hex())
        logging.error(f"Erro no swap: {str(e)}")
        return False

def check_pending_transactions():
    """Verifica e limpa transações pendentes antigas."""
    try:
        for tx_hash in list(pending_transactions):
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                if receipt is not None:
                    pending_transactions.remove(tx_hash)
            except:
                # Se a transação não for encontrada, remove após 1 hora
                if time.time() - int(tx_hash[-8:], 16) > 3600:
                    pending_transactions.remove(tx_hash)
    except Exception as e:
        logging.error(f"Erro ao verificar transações pendentes: {str(e)}")

def arbitrage_cycle():
    """Ciclo completo de arbitragem com verificações de segurança."""
    try:
        if not is_connected():
            return False

        # Verifica transações pendentes antes de continuar
        check_pending_transactions()
        if pending_transactions:
            logging.warning(f"Aguardando {len(pending_transactions)} transações pendentes...")
            return False

        amount_in = int(TRADE_AMOUNT * 10**18)
        
        # Obtém preços de forma segura
        price_pancake = get_price(
            VERIFIED_CONTRACTS["DEX_ROUTERS"]["PancakeSwap"],
            VERIFIED_CONTRACTS["TOKENS"]["BNB"],
            VERIFIED_CONTRACTS["TOKENS"]["USDT"],
            amount_in
        )
        
        if not price_pancake:
            return False
            
        price_ape = get_price(
            VERIFIED_CONTRACTS["DEX_ROUTERS"]["ApeSwap"],
            VERIFIED_CONTRACTS["TOKENS"]["USDT"],
            VERIFIED_CONTRACTS["TOKENS"]["BNB"],
            price_pancake
        )
        
        if not price_ape:
            return False

        # Calcula lucro considerando slippage
        effective_price_ape = price_ape * (100 - MAX_SLIPPAGE) / 100
        profit = (price_pancake - effective_price_ape) / 10**18
        gas_cost_bnb, gas_cost_usdt = calculate_gas_cost()
        
        logging.info(
            f"Análise de arbitragem:\n"
            f"- Vender no PancakeSwap: {price_pancake/10**18:.6f} USDT\n"
            f"- Comprar no ApeSwap: {effective_price_ape/10**18:.6f} USDT (com slippage)\n"
            f"- Lucro potencial: {profit:.6f} USDT\n"
            f"- Custo estimado: {gas_cost_usdt:.6f} USDT"
        )

        required_profit = max(MIN_PROFIT_USDT, gas_cost_usdt * 3)
        if profit > required_profit:
            logging.info("Iniciando arbitragem...")
            
            # Executa a estratégia com proteções
            if execute_swap(
                router_pancake,
                VERIFIED_CONTRACTS["TOKENS"]["BNB"],
                VERIFIED_CONTRACTS["TOKENS"]["USDT"],
                amount_in,
                profit
            ):
                if execute_swap(
                    router_ape,
                    VERIFIED_CONTRACTS["TOKENS"]["USDT"],
                    VERIFIED_CONTRACTS["TOKENS"]["BNB"],
                    price_pancake,
                    profit
                ):
                    net_profit = profit - gas_cost_usdt * 2  # Considera 2 transações
                    logging.info(f"Arbitragem concluída! Lucro líquido: {net_profit:.6f} USDT")
                    return True
        else:
            logging.info("Sem oportunidades lucrativas suficientes")
            
    except Exception as e:
        logging.error(f"Erro no ciclo de arbitragem: {str(e)}")
    
    return False

def main():
    """Loop principal com controle de execução."""
    logging.info("Iniciando bot de arbitragem BSC com proteções avançadas...")
    
    # Verificação inicial de segurança
    if not is_connected():
        logging.error("Não foi possível conectar à blockchain")
        return
        
    if not WALLET_ADDRESS or not PRIVATE_KEY:
        logging.error("Configuração de carteira não encontrada")
        return
    
    # Aprovações iniciais apenas dos valores necessários
    initial_approval_amount = int(TRADE_AMOUNT * 2 * 10**18)  # Margem de 2x
    
    if not approve_token(
        VERIFIED_CONTRACTS["TOKENS"]["USDT"],
        VERIFIED_CONTRACTS["DEX_ROUTERS"]["PancakeSwap"],
        initial_approval_amount
    ):
        return
        
    if not approve_token(
        VERIFIED_CONTRACTS["TOKENS"]["USDT"],
        VERIFIED_CONTRACTS["DEX_ROUTERS"]["ApeSwap"],
        initial_approval_amount
    ):
        return
    
    # Loop principal
    while True:
        try:
            arbitrage_cycle()
            time.sleep(15)  # Intervalo entre verificações
            
        except KeyboardInterrupt:
            logging.info("Bot interrompido manualmente")
            break
        except Exception as e:
            logging.error(f"Erro crítico: {str(e)}")
            time.sleep(60)

if __name__ == "__main__":
    main()
