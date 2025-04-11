#!/usr/bin/env python3
import os
import json
import time
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from web3 import Web3
from web3.exceptions import ContractLogicError
from itertools import permutations

# === Logging ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('/var/log/arbitrage.log', maxBytes=5 * 1024 * 1024, backupCount=3),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# === Load Env ===
load_dotenv('.env.local')

# === Config ===
CONFIG = {
    "RPC_URL": os.getenv("ETH_RPC_URL", "https://mainnet.infura.io/v3/YOUR_INFURA_KEY"),
    "WALLET_ADDRESS": os.getenv("WALLET_ADDRESS"),
    "PRIVATE_KEY": os.getenv("PRIVATE_KEY"),
    "TRADE_AMOUNT_ETH": float(os.getenv("TRADE_AMOUNT_ETH", 0.1))
}

# === Web3 Setup ===
w3 = Web3(Web3.HTTPProvider(CONFIG["RPC_URL"]))
if not w3.is_connected():
    logger.error("Erro: Não foi possível conectar ao RPC.")
    exit(1)

# === Addresses ===
ASSETS = {
    "WETH": Web3.to_checksum_address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),
    "USDC": Web3.to_checksum_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
    "USDT": Web3.to_checksum_address("0xdAC17F958D2ee523a2206206994597C13D831ec7"),
    "DAI":  Web3.to_checksum_address("0x6B175474E89094C44Da98b954EedeAC495271d0F"),
    "WBTC": Web3.to_checksum_address("0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599")
}

ROUTER_ADDRESS = Web3.to_checksum_address("0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")  # Uniswap V2 Router

# === ABIs ===
ROUTER_ABI = json.loads('[{"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"type":"function"}]')

# === Contracts ===
router_contract = w3.eth.contract(address=ROUTER_ADDRESS, abi=ROUTER_ABI)

# === Safe Swap Check ===
def get_amounts_out_safe(amount_in, path):
    try:
        if amount_in <= 0:
            raise ValueError("amount_in deve ser maior que zero.")
        return router_contract.functions.getAmountsOut(amount_in, path).call()
    except ContractLogicError as e:
        logger.warning(f"Erro em getAmountsOut: {str(e)}")
    except Exception as e:
        logger.warning(f"Erro inesperado: {str(e)}")
    return None

# === Arbitragem Triangular ===
def check_triangular_arbitrage():
    base_token = "WETH"
    amount_in = w3.to_wei(CONFIG["TRADE_AMOUNT_ETH"], 'ether')

    logger.info(f"Iniciando bot de arbitragem triangular com {CONFIG['TRADE_AMOUNT_ETH']} ETH")

    tokens = [k for k in ASSETS.keys() if k != base_token]

    # Gera todas as combinações possíveis de 3 tokens distintos, sem repetir o base
    for t1, t2, t3 in permutations(tokens, 3):
        path = [ASSETS[base_token], ASSETS[t1], ASSETS[t2], ASSETS[t3], ASSETS[base_token]]

        # Garante que o caminho não tenha tokens consecutivos iguais
        if len(set(path)) != len(path) - 1:  # permite apenas o primeiro e o último iguais
            continue

        amounts = get_amounts_out_safe(amount_in, path)
        if amounts:
            final_amount = amounts[-1]
            profit = final_amount - amount_in
            if profit > 0:
                profit_eth = w3.from_wei(profit, 'ether')
                logger.info(f"[OPORTUNIDADE] {base_token}->{t1}->{t2}->{t3}->{base_token} | Lucro: {profit_eth:.10f} ETH")


# === Execução ===
if __name__ == "__main__":
    try:
        while True:
            check_triangular_arbitrage()
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Execução interrompida pelo usuário.")
