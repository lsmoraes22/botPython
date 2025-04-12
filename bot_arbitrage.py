#!/usr/bin/env python
import os
import time
import json
import logging
from logging.handlers import RotatingFileHandler
import sys
from web3 import Web3
from dotenv import load_dotenv
from eth_account import Account
from web3.middleware import SignAndSendRawMiddlewareBuilder, ExtraDataToPOAMiddleware

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'arbitrage.log',
            maxBytes=5*1024*1024,  # 5MB por arquivo
            backupCount=3          # Mantém 3 arquivos antigos
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Carrega variáveis de ambiente
load_dotenv('.env.local')

# Configurações
CONFIG = {
    "BSC_RPC": os.getenv("BSC_RPC", "https://bsc-dataseed.binance.org/"),
    "WALLET_ADDRESS": os.getenv("WALLET_ADDRESS"),
    "PRIVATE_KEY": os.getenv("PRIVATE_KEY"),
    "MIN_PROFIT_USDT": float(os.getenv("MIN_PROFIT_USDT", 0.5)),
    "TRADE_AMOUNT": float(os.getenv("TRADE_AMOUNT", 0.1)),
    "MAX_SLIPPAGE": float(os.getenv("MAX_SLIPPAGE", 1.0)),
    "GAS_LIMIT": int(os.getenv("GAS_LIMIT", 250000)),
}

# Contratos e ABIs
CONTRACTS = {
    "BNB": Web3.to_checksum_address("0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"),
    "USDT": Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955"),
    "PancakeSwap": Web3.to_checksum_address("0x10ED43C718714eb63d5aA57B78B54704E256024E"),
    "ApeSwap": Web3.to_checksum_address("0xcF0feBd3f17CEf5b47b0cD257aCf6025c5BFf3b7")
}

ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]')
ROUTER_ABI = json.loads('[{"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"type":"function"}]')

class BSCArbitrageBot:
    def __init__(self):
        self.w3 = None
        self.account = None
        self.setup_web3()
        self.validate_wallet()
        self.init_contracts()

    def setup_web3(self):
        """Inicializa Web3 e middlewares"""
        self.w3 = Web3(Web3.HTTPProvider( CONFIG["BSC_RPC"], request_kwargs={'timeout': 30} ))

        # Carrega conta a partir da chave privada
        self.account = self.w3.eth.account.from_key(CONFIG["PRIVATE_KEY"])
        self.w3.eth.default_account = self.account.address

        # Assina transações automaticamente
        self.w3.middleware_onion.inject(
            SignAndSendRawMiddlewareBuilder.build(self.account),
            layer=0
        )

        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    def validate_wallet(self):
        if not CONFIG["PRIVATE_KEY"] or not CONFIG["WALLET_ADDRESS"]:
            logger.error("Configuração da carteira incompleta")
            sys.exit(1)

        if self.account.address.lower() != CONFIG["WALLET_ADDRESS"].lower():
            logger.error("Chave privada não corresponde ao endereço da carteira")
            sys.exit(1)

    def init_contracts(self):
        """Inicializa instâncias dos contratos usados"""
        self.contracts = {
            "pancake": self.w3.eth.contract(address=CONTRACTS["PancakeSwap"], abi=ROUTER_ABI),
            "ape": self.w3.eth.contract(address=CONTRACTS["ApeSwap"], abi=ROUTER_ABI),
            "usdt": self.w3.eth.contract(address=CONTRACTS["USDT"], abi=ERC20_ABI),
        }

    def health_check(self):
        """Verifica se a conexão está saudável"""
        try:
            start = time.time()
            block = self.w3.eth.get_block('latest')
            latency = time.time() - start

            return {
                "connected": True,
                "latency": latency,
                "block": block['number'],
                "balance": self.w3.eth.get_balance(self.account.address)
            }
        except Exception as e:
            logger.warning(f"Falha na verificação de saúde: {str(e)}")
            return {"connected": False}

    def check_arbitrage(self):
        """Exemplo básico de verificação de arbitragem"""
        amount_in = self.w3.to_wei(CONFIG["TRADE_AMOUNT"], 'ether')
        path = [CONTRACTS["BNB"], CONTRACTS["USDT"]]

        try:
            pancake_out = self.contracts["pancake"].functions.getAmountsOut(amount_in, path).call()
            ape_out = self.contracts["ape"].functions.getAmountsOut(amount_in, path).call()

            usdt_pancake = self.w3.from_wei(pancake_out[-1], 'ether')
            usdt_ape = self.w3.from_wei(ape_out[-1], 'ether')

            logger.info(f"PancakeSwap: {usdt_pancake:.4f} USDT | ApeSwap: {usdt_ape:.4f} USDT")

            diff = abs(usdt_pancake - usdt_ape)
            if diff >= CONFIG["MIN_PROFIT_USDT"]:
                logger.info(f"Arbitragem detectada! Diferença: {diff:.4f} USDT")
            else:
                logger.info("Sem oportunidade de arbitragem no momento.")
        except Exception as e:
            logger.error(f"Erro ao verificar arbitragem: {str(e)}")

    def run(self):
        logger.info(f"Iniciando bot de arbitragem para {self.account.address}")
        while True:
            try:
                health = self.health_check()

                if not health["connected"]:
                    logger.warning("Sem conexão. Tentando novamente...")
                    time.sleep(10)
                    continue

                logger.info(f"Conexão OK | Bloco: {health['block']} | BNB: {self.w3.from_wei(health['balance'], 'ether'):.4f}")
                self.check_arbitrage()

                time.sleep(10)

            except KeyboardInterrupt:
                logger.info("Execução interrompida pelo usuário.")
                break
            except Exception as e:
                logger.error(f"Erro inesperado: {str(e)}")
                time.sleep(30)

if __name__ == "__main__":
    try:
        bot = BSCArbitrageBot()
        bot.run()
    except Exception as e:
        logger.error(f"Erro ao iniciar o bot: {str(e)}")
        sys.exit(1)
