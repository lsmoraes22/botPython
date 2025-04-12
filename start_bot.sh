#!/bin/bash
cd /home/lucas/botPython
source venv/bin/activate

# Roda os dois scripts em background e registra logs separados
python bot_arbitrage.py >> arbitrage.log 2>&1 &
python triangular.py >> arbitrage.log 2>&1 &
wait
