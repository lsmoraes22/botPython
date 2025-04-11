#!/usr/bin/env python3
import os
import time
import logging
from logging.handlers import RotatingFileHandler
from web3 import Web3
from dotenv import load_dotenv
from datetime import datetime

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'conversor_diario_secure.log',
            maxBytes=5*1024*1024,
            backupCount=3
        ),
        logging.StreamHandler()
    ]
)

# Carregar variáveis de ambiente
load_dotenv('.env.local')

# Conectar ao Web3
def connect_web3():
    w3 = Web3(Web3.HTTPProvider(
        os.getenv("BSC_RPC", "https://bsc-dataseed.binance.org/"),
        request_kwargs={'timeout': 60}
    ))
    if w3.is_connected():
        return w3
    else:
        logging.error("Falha na conexão com a blockchain")
        return None

web3 = connect_web3()

# Endereços dos tokens
TOKENS = {
    "BNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    "USDT": "0x55d398326f99059fF775485246999027B3197955"
}

# ABI mínima para ERC20
ERC20_ABI = [...]  # ABI conforme definido anteriormente

# Função para obter saldo
def get_balance(token_address):
    if token_address == TOKENS["BNB"]:
        return web3.eth.get_balance(os.getenv("WALLET_ADDRESS"))
    contract = web3.eth.contract(address=token_address, abi=ERC20_ABI)
    return contract.functions.balanceOf(os.getenv("WALLET_ADDRESS")).call()

# Função principal
def main():
    logging.info("Iniciando conversão diária de USDT para BNB")

    # Verificar conexão
    if not web3 or not web3.is_connected():
        logging.error("Não foi possível conectar à blockchain")
        return

    # Obter saldo inicial de BNB
    saldo_inicial_bnb = get_balance(TOKENS["BNB"])

    # Aqui você pode chamar a função de conversão de USDT para BNB
    # converter_usdt_para_bnb()

    # Obter saldo final de BNB
    saldo_final_bnb = get_balance(TOKENS["BNB"])

    # Calcular ganho diário
    ganho_diario = saldo_final_bnb - saldo_inicial_bnb

    # Registrar no log
    logging.info(f"Saldo inicial de BNB: {Web3.from_wei(saldo_inicial_bnb, 'ether'):.6f}")
    logging.info(f"Saldo final de BNB: {Web3.from_wei(saldo_final_bnb, 'ether'):.6f}")
    logging.info(f"Ganho diário: {Web3.from_wei(ganho_diario, 'ether'):.6f} BNB")

if __name__ == "__main__":
    main()

