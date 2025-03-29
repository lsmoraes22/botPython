import os
import time
import json
from web3 import Web3
from web3.middleware import geth_poa_middleware
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# Configurações da BSC
BSC_RPC = "https://bsc-dataseed.binance.org/"
WALLET_ADDRESS = os.getenv('WALLET_ADDRESS')
PRIVATE_KEY = os.getenv('PRIVATE_KEY')  # Nunca exponha no código!

# Conecta à BSC
web3 = Web3(Web3.HTTPProvider(BSC_RPC))
web3.middleware_onion.inject(geth_poa_middleware, layer=0)  # Necessário para BSC

# Contratos dos Tokens (BSC)
TOKENS = {
    'BNB': '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c',  # BNB
    'USDT': '0x55d398326f99059fF775485246999027B3197955',  # USDT
}

# Contratos das DEXs (Routers)
DEX_ROUTERS = {
    'PancakeSwap': '0x10ED43C718714eb63d5aA57B78B54704E256024E',
    'ApeSwap': '0xcF0feBd3f17CEf5b47b0cD257aCf6025c5BFf3b7',
}

# ABIs (simplificadas)
ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}, {"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"}]')
ROUTER_ABI = json.loads('[{"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"type":"function"}, {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"type":"function"}]')

def get_balance(token_address):
    if token_address.lower() == 'bnb':
        return web3.eth.get_balance(WALLET_ADDRESS)
    contract = web3.eth.contract(address=token_address, abi=ERC20_ABI)
    return contract.functions.balanceOf(WALLET_ADDRESS).call()
    
def approve_token(token_address, spender, amount=2**256-1):
    contract = web3.eth.contract(address=token_address, abi=ERC20_ABI)
    tx = contract.functions.approve(spender, amount).buildTransaction({
        'chainId': 56,  # BSC
        'gas': 100000,
        'gasPrice': web3.eth.gas_price,
        'nonce': web3.eth.getTransactionCount(WALLET_ADDRESS),
    })
    signed_tx = web3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
    return tx_hash
    
def get_price(router_address, token_in, token_out, amount_in):
    router = web3.eth.contract(address=router_address, abi=ROUTER_ABI)
    path = [token_in, token_out]
    amounts = router.functions.getAmountsOut(amount_in, path).call()
    return amounts[-1]  # Retorna o amount_out
    
def execute_swap(router_address, token_in, token_out, amount_in, slippage=0.5):
    router = web3.eth.contract(address=router_address, abi=ROUTER_ABI)
    path = [token_in, token_out]
    amount_out_min = int(get_price(router_address, token_in, token_out, amount_in) * (100 - slippage) / 100)
    
    tx = router.functions.swapExactTokensForTokens(
        amount_in,
        amount_out_min,
        path,
        WALLET_ADDRESS,
        int(time.time()) + 1200  # Deadline (20 minutos)
    ).buildTransaction({
        'chainId': 56,  # BSC
        'gas': 200000,
        'gasPrice': web3.eth.gas_price,
        'nonce': web3.eth.getTransactionCount(WALLET_ADDRESS),
    })
    
    signed_tx = web3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
    return tx_hash

def pendular_arbitrage():
    bnb_address = TOKENS['BNB']
    usdt_address = TOKENS['USDT']
    amount_in = 1 * 10**18  # 1 BNB (em wei)
    
    # Aprova USDT para ser gasto nas DEXs
    approve_token(usdt_address, DEX_ROUTERS['PancakeSwap'])
    approve_token(usdt_address, DEX_ROUTERS['ApeSwap'])
    
    while True:
        try:
            # 1. Verifica preços de venda (BNB → USDT)
            sell_price_pancake = get_price(DEX_ROUTERS['PancakeSwap'], bnb_address, usdt_address, amount_in)
            sell_price_ape = get_price(DEX_ROUTERS['ApeSwap'], bnb_address, usdt_address, amount_in)
            
            # 2. Verifica preços de compra (USDT → BNB)
            buy_price_pancake = get_price(DEX_ROUTERS['PancakeSwap'], usdt_address, bnb_address, sell_price_pancake)
            buy_price_ape = get_price(DEX_ROUTERS['ApeSwap'], usdt_address, bnb_address, sell_price_ape)
            
            # 3. Se PancakeSwap paga mais USDT por BNB (venda) e ApeSwap vende BNB mais barato (compra)
            if sell_price_pancake > sell_price_ape and buy_price_ape > amount_in:
                print(f"🚀 Vendendo BNB na PancakeSwap por {sell_price_pancake/1e18} USDT")
                execute_swap(DEX_ROUTERS['PancakeSwap'], bnb_address, usdt_address, amount_in)
                
                print(f"🔄 Comprando BNB na ApeSwap por {buy_price_ape/1e18} USDT")
                execute_swap(DEX_ROUTERS['ApeSwap'], usdt_address, bnb_address, sell_price_pancake)
                
                print(f"✅ Lucro: {(sell_price_pancake - buy_price_ape)/1e18} USDT")
            
            time.sleep(5)  # Espera 5 segundos
        
        except Exception as e:
            print(f"Erro: {e}")
            time.sleep(10)
            
if __name__ == "__main__":
    print("Iniciando bot de arbitragem pendular...")
    pendular_arbitrage()