import aiohttp
import asyncio
import ssl
import certifi
from decimal import Decimal
import time
import os
import telebot
from telebot import types
from config import telegram_bot_token
import logging
import time
import asyncio
from aiohttp import ClientSession
from config import CG_API_KEY,RPC_URL
import threading

#headers = {'x-cg-pro-api-key': CG_API_KEY}

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Your bot's token
API_TOKEN = telegram_bot_token

bot = telebot.TeleBot(API_TOKEN, parse_mode=None)

async def get_token_price_in_usd(session, token_address):
    logger.debug(f"Fetching token price for address: {token_address}")
    await asyncio.sleep(.01)  # Respectful delay to avoid rate limiting
    url = f"https://pro-api.coingecko.com/api/v3/simple/token_price/ethereum?contract_addresses={token_address}&vs_currencies=usd"
    
    headers = {'x-cg-pro-api-key': CG_API_KEY}
    
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                price_in_usd = data[token_address.lower()]['usd']
                logger.info(f"Price for {token_address}: USD {price_in_usd}")
                return Decimal(price_in_usd)
            else:
                logger.warning(f"Failed to fetch price for {token_address}. Status code: {response.status}")
                return Decimal("0.00")
    except Exception as e:
        logger.error(f"Error during token price fetch for {token_address}: {e}", exc_info=True)
        return Decimal("0.00")

async def get_eth_price_in_usd(session):
    logger.debug("Fetching ETH price in USD")
    url = f"https://pro-api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
    
    headers = {'x-cg-pro-api-key': CG_API_KEY}
    
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                price_in_usd = data['ethereum']['usd']
                logger.info(f"ETH price in USD: {price_in_usd}")
                return Decimal(price_in_usd)
            else:
                logger.warning(f"Failed to fetch ETH price. Status code: {response.status}")
                return Decimal("0.00")
    except Exception as e:
        logger.error("Failed to fetch ETH price", exc_info=True)
        return Decimal("0.00")


async def fetch_token_data(session, url, payload, retries=3, delay=0.01):
    logger.debug(f"Fetching token data with payload: {payload}")
    for attempt in range(retries):
        try:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.warning(f"Error during token data fetch. Attempt: {attempt+1}. Status code: {response.status}")
            await asyncio.sleep(delay)
        except aiohttp.ClientError as e:
            logger.error(f"AIOHTTP client error on attempt {attempt+1}", exc_info=True)
            await asyncio.sleep(2 ** attempt)
    return None

async def fetch_eth_balance(session, url, account_address):
    logger.debug(f"Fetching ETH balance for address: {account_address}")
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getBalance",
        "params": [account_address, "latest"],
        "id": 1
    }
    try:
        async with session.post(url, json=payload) as response:
            if response.status == 200:
                result = await response.json()
                logger.info(f"ETH balance for {account_address}: {result}")
                return result
            else:
                logger.warning(f"Failed to fetch ETH balance for {account_address}. Status code: {response.status}")
    except aiohttp.ClientError as e:
        logger.error(f"Client error while fetching ETH balance for address: {account_address}: {e}", exc_info=True)
    return None

async def fetch_all_token_data(session, rpc_url, tokens, account_address):
    logger.debug(f"Fetching all token data for address: {account_address}")
    tasks = []
    for token in tokens:
        if token['chainId'] == 1:
            data_field = f"0x70a08231{''.join(['0']*(64-len(account_address[2:])))+account_address[2:]}"
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": token['address'], "data": data_field}, "latest"],
                "id": 1
            }
            tasks.append(fetch_token_data(session, rpc_url, payload, delay=0.01))
    return await asyncio.gather(*tasks)

async def main(account_address, message):
    logger.info(f"Starting main function for account: {account_address}")
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    directory = "/Users/eos/Desktop/PythonApps/CUH_TELEGRAM/substreams_wallet_db"
    os.makedirs(directory, exist_ok=True)

    filename = f"{directory}/{account_address}.txt"
    
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            token_list_url = "https://tokens.coingecko.com/uniswap/all.json"
            async with session.get(token_list_url) as response:
                if response.status == 200:
                    token_list = await response.json()
                    # Filter out the YV1INCH token from the list
                    token_list = [token for token in token_list.get('tokens', []) if token['chainId'] == 1 and token['symbol'] != 'YV1INCH']
                else:
                    logger.warning("Failed to fetch token list. Exiting main function.")
                    return

            with open(filename, "w") as file:
                rpc_url = RPC_URL
                
                eth_price_usd = await get_eth_price_in_usd(session)
                eth_balance_result = await fetch_eth_balance(session, rpc_url, account_address)
                total_wallet_value = Decimal("0.00")
                
                if eth_balance_result and 'result' in eth_balance_result:
                    eth_balance = Decimal(int(eth_balance_result['result'], 16)) / Decimal(10**18)
                    eth_value_usd = eth_balance * eth_price_usd
                    total_wallet_value += eth_value_usd
                    file.write(f"\nETH\n{eth_balance:.2f} @ $ {eth_price_usd:,.2f}\n$ {eth_value_usd:,.2f}\n\n")

                token_data_responses = await fetch_all_token_data(session, rpc_url, token_list, account_address)
                for token, token_data in zip(token_list, token_data_responses):
                    if token_data and 'result' in token_data and token_data['result'] != '0x':
                        raw_balance = Decimal(int(token_data['result'], 16))
                        if raw_balance == 0:
                            continue
                        token_decimals = token.get('decimals', 18)
                        token_balance = raw_balance / (10 ** token_decimals)
                        token_price_usd = await get_token_price_in_usd(session, token['address'])
                        total_value_usd = token_balance * token_price_usd
                        total_wallet_value += total_value_usd
                        balance_str = "∞" if token_balance > 10_000_000 else "{:,.2f}".format(token_balance)
                        total_value_str = "∞" if total_value_usd > 1_000_000 else "${:,.2f}".format(total_value_usd)
                        file.write(f"{token.get('symbol', 'N/A')}\n{balance_str} @ $ {token_price_usd:,.2f}\n{total_value_str}\n\n")

                file.write(f"Total Wallet Value: $ {total_wallet_value:,.2f}\n")
                logger.info(f"Total wallet value for {account_address}: $ {total_wallet_value:,.2f}")

    except Exception as e:
        logger.error("An error occurred during the main function execution", exc_info=True)

    try:
        with open(filename, "r") as file:
            result_text = file.read()
            bot.send_message(message.chat.id, result_text)
            logger.debug("Sent wallet data to user")
    except Exception as e:
        logger.error("Failed to send message with wallet data", exc_info=True)

@bot.message_handler(commands=['balance'])
def ask_for_address(message):
    logger.debug(f"Received balance command from {message.chat.id}")
    try:
        msg = bot.reply_to(message, "Enter an ETH Address: ")
        bot.register_next_step_handler(msg, process_address_step)
    except Exception as e:
        logger.error("Error in ask_for_address function", exc_info=True)

def process_address_step(message):
    logger.debug(f"Processing address step for message: {message.text}")
    try:
        account_address = message.text.strip()
        # Send immediate feedback to the user
        bot.send_message(message.chat.id, "Processing your request...")
        asyncio.run(main(account_address, message))
    except Exception as e:
        logger.error("Failed to process address step", exc_info=True)
        bot.reply_to(message, 'Oops. Something went wrong.')


if __name__ == '__main__':
    try:
        logger.info("Bot polling started")
        t = threading.Thread(target=lambda: bot.polling(none_stop=True))
        t.start()
    except Exception as e:
        logger.error("An error occurred in the bot's main loop", exc_info=True)


                       
