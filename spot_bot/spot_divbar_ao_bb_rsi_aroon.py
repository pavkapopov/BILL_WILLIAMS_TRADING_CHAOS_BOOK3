"""Торговый бот по идеям Билла Вильямса Торговый хаос 2. Дивергентный бар, RSI, AROON, АО, определение ангуляции по Боллинджеру."""
import json
import time
import datetime
from urllib.parse import urljoin, urlencode
import hmac, hashlib
import requests
import numpy as np
import websocket
import pandas as pd

#общие настройки
#если настроен телеграм бот, то раскомментируйте строку № 207
TELEGRAM_TOKEN = ''
TELEGRAM_CHANNEL_ID = ''
API_KEY = ''
API_SECRET = ''
BASE_URL = 'https://api.binance.com'
PATH = '/api/v3/order'
headers = {'X-MBX-APIKEY': API_KEY}

trade_symbol = "ADAUSDT" #торговая пара
trade_symbol_low = trade_symbol.lower() #торговая пара в нижнем регистре для передечи в websocket
bar_interval = "5m" #таймфрейм бара для анализа
#BTCUSDT 0.00035
#ETHUSDT  0.0055
trade_quantity = 70 # количество базовой валюты для покупки. должна быть больше по стоимости чем MIN_NOTIONAL т.е. trade_quantity * last_price > MIN_NOTIONAL
                      #и больше minQty смотрим тут https://www.binance.com/api/v3/exchangeInfo
                      # MIN_NOTIONAL смотрим тут https://www.binance.com/api/v3/exchangeInfo

class BinanceException(Exception):
    def __init__(self, status_code, data):

        self.status_code = status_code
        if data:
            self.code = data['code']
            self.msg = data['msg']
        else:
            self.code = None
            self.msg = None
        message = f"{status_code} [{self.code}] {self.msg}"

        # Python 2.x
        # super(BinanceException, self).__init__(message)
        super().__init__(message)

#функия ищет количество десятичных знаков для round() чтобы округлить цену до нужных параметров биржи
def dStepSize(no_str):
    if "." in no_str:
         return len(no_str.split(".")[1].rstrip("0"))
    else:
         return 0

def get_RSI(ohlc_df, lookback = 14, ema = True):
    
    if len(ohlc_df) < lookback:
        return [np.nan]*len(ohlc_df)

    close_delta = ohlc_df.close.diff()

    # Make two series: one for lower closes and one for higher closes
    up = close_delta.clip(lower=0)
    down = -1 * close_delta.clip(upper=0)
    
    if ema == True:
	    # Use exponential moving average
        ma_up = up.ewm(com = lookback - 1, adjust=True, min_periods = lookback).mean()
        ma_down = down.ewm(com = lookback - 1, adjust=True, min_periods = lookback).mean()
    else:
        # Use simple moving average
        ma_up = up.rolling(window = lookback, adjust=False).mean()
        ma_down = down.rolling(window = lookback, adjust=False).mean()
        
    rsi = ma_up / ma_down
    rsi = 100 - (100/(1 + rsi))
    return rsi

def get_AROON(ohlc_df, lookback=25):
    
    if len(ohlc_df) < lookback:
        return [np.nan]*len(ohlc_df)
    
    aroon_up = 100 * ohlc_df.high.rolling(lookback + 1).apply(lambda x: x.argmax()) / lookback
    aroon_down = 100 * ohlc_df.low.rolling(lookback + 1).apply(lambda x: x.argmin()) / lookback
    
    return aroon_up, aroon_down

# функция определяет есть ли пересечение бара с ma
def sma_crossing_bar(high,low,sma):
    if sma < high and sma >low:
        return True
    else:
        return False

# функция отправки сообщения в Telegram
def send_telegram(text: str):
    token = TELEGRAM_TOKEN
    url = "https://api.telegram.org/bot"
    channel_id = TELEGRAM_CHANNEL_ID
    url += token
    method = url + "/sendMessage"

    r = requests.post(method, data={ "chat_id": channel_id, "text": text})

    if r.status_code != 200:
        print (r.status_code)
        raise Exception("post_text error")


print("Получаем параметры валютной пары...")
exchangeInfo = requests.get("https://www.binance.com/api/v3/exchangeInfo").json()

dict_exchangeInfo = {"minPrice": 0, "tickSize": 0, "minQty": 0, "stepSize": 0, "minNotional": 0}

for ticker in exchangeInfo["symbols"]:
    if str(ticker["symbol"]) == trade_symbol:
        for f in ticker["filters"]:
            if str(f["filterType"]) == "PRICE_FILTER":
                dict_exchangeInfo["minPrice"] = f["minPrice"]
                dict_exchangeInfo["tickSize"] = f["tickSize"]
            if str(f["filterType"]) == "LOT_SIZE":
                dict_exchangeInfo["minQty"] = f["minQty"]
                dict_exchangeInfo["stepSize"] = f["stepSize"]
            if str(f["filterType"]) == "MIN_NOTIONAL":
                dict_exchangeInfo["minNotional"] = f["minNotional"]

tickSize = dStepSize(dict_exchangeInfo["tickSize"]) #шаг цены до которой надо округлять цену для высталвения ордера
                                                    #tickSize смотрим тут https://www.binance.com/api/v3/exchangeInfo

price = requests.get("https://www.binance.com/api/v3/ticker/price?symbol=" + trade_symbol).json()


#if float(price["price"]) * float(trade_quantity) < float(dict_exchangeInfo["minNotional"]):
#    if float(dict_exchangeInfo["minNotional"]) / float(price["price"]) < float(dict_exchangeInfo["minQty"])
#        print("Количество базовой валюты не достаточно для торгов, необходимо минимум", float(dict_exchangeInfo["minQty"]))
#    exit()

print("Параметры валютной пары",trade_symbol,"получены, можно торговать...",dict_exchangeInfo)

order_id = 0
order_status = ""
client_orderid = ""

def on_message(ws, message):
   
    trade = json.loads(message)

    if trade['e'] == "kline":
        is_this_kline_closed = trade['k']['x']

    if is_this_kline_closed:
        time.sleep(0.2)
        #опрееляем тренд по aroon, для торговли на тф 5м, рекомендуют определять тренд по тф 4ч
        jsonKlines_4h = requests.get("https://api.binance.com/api/v3/klines?symbol=" + trade_symbol + "&interval=4h&limit=102").json()
        dfKlines_4h = pd.DataFrame(jsonKlines_4h, columns=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','buy_asset_volume','buy_quote_volume','ignore'])
        dfKlines_4h = dfKlines_4h.astype(float)
        dfKlines_4h.set_index(keys=pd.to_datetime(dfKlines_4h['open_time'], unit='ms'), inplace=True)
        dfKlines_4h.drop(columns=['open_time','volume','close_time','quote_volume','trades','buy_asset_volume','buy_quote_volume','ignore'],inplace=True)

        # определяем тренд на тф 4 часа
        aroon_up_4h, aroon_down_4h = get_AROON(dfKlines_4h, 25)
        aroon_trend_up_4h = True if aroon_up_4h.iloc[-1] > 90 and aroon_down_4h.iloc[-1] < 30 else False
        aroon_trend_down_4h = True if aroon_down_4h.iloc[-1] > 90 and aroon_up_4h.iloc[-1] < 30 else False

        # получаем последние свечи для расчёта стратегии
        jsonKlines = requests.get("https://api.binance.com/api/v3/klines?symbol=" + trade_symbol + "&interval=" + bar_interval + "&limit=102").json()
        dfKlines = pd.DataFrame(jsonKlines, columns=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','buy_asset_volume','buy_quote_volume','ignore'])
        dfKlines = dfKlines.astype(float)
        # вычисляем среднюю цену баров
        dfAveragePrice = (dfKlines.high + dfKlines.low)/2
        # вычисляем Awesome Oscillator
        sma5 = dfAveragePrice.rolling(window=5).mean()
        sma34 = dfAveragePrice.rolling(window=34).mean()
        ao = sma5 - sma34

        # вычисляем RSI
        dfRSI_5m = get_RSI(dfKlines)

        close_in_interval = 0 # иногда определение интервала не срабатывает. Чтобы небыло ошибки неизвестной переменной
        # определяем является ли бар дивергентным
        interval = (dfKlines.high.iloc[-2] - dfKlines.low.iloc[-2]) / 2

        if dfKlines.high.iloc[-2] > dfKlines.close.iloc[-2] and dfKlines.close.iloc[-2] > dfKlines.high.iloc[-2] - interval or dfKlines.high.iloc[-2] == dfKlines.close.iloc[-2]:
            close_in_interval = 1
        if dfKlines.close.iloc[-2] > dfKlines.low.iloc[-2] + interval and dfKlines.high.iloc[-2] - interval > dfKlines.close.iloc[-2]:
            close_in_interval = 2
        if dfKlines.close.iloc[-2] > dfKlines.low.iloc[-2] and dfKlines.low.iloc[-2] + interval > dfKlines.close.iloc[-2] or dfKlines.close.iloc[-2] == dfKlines.low.iloc[-2]:
            close_in_interval = 3
        # Боллинджер
        sma20 = dfAveragePrice.rolling(window=20).mean()
        bb_up = sma20 + dfKlines.close.rolling(window=20).std()*2
        bb_low = sma20 - dfKlines.close.rolling(window=20).std()*2
        # определяем "пробил" бар нижнюю линию Боллинджера
        bb_low_crossing_bar = sma_crossing_bar(dfKlines.high.iloc[-2],dfKlines.low.iloc[-2],bb_low.iloc[-2])
        # определяем "пробил" бар верхнюю линию Боллинджера
        bb_up_crossing_bar = sma_crossing_bar(dfKlines.high.iloc[-2],dfKlines.low.iloc[-2],bb_up.iloc[-2])

        print(aroon_up_4h.iloc[-1],aroon_down_4h.iloc[-1],dfRSI_5m.iloc[-1])

        # условие на покупку в лонг
        if (close_in_interval == 1
            and ao.iloc[-3] > ao.iloc[-2]
            and ao.iloc[-2] < 0
            and bb_low_crossing_bar
            and dfRSI_5m.iloc[-1] < 30
            and aroon_trend_up_4h):

                timestamp = requests.get("https://api.binance.com/api/v3/time").json()
                params = {'symbol': trade_symbol,'side': 'BUY','type': 'MARKET','quantity': trade_quantity,'recvWindow': 5000,'timestamp': timestamp['serverTime']}
                query_string = urlencode(params)
                params['signature'] = hmac.new(API_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
                url = urljoin(BASE_URL, PATH)
                r = requests.post(url, headers=headers, params=params)
                if r.status_code == 200:
                    data = r.json()
                    price_buy_long = float(data["fills"][0]["price"])
                    trade_time = datetime.datetime.utcfromtimestamp(timestamp['serverTime']/1000).replace(tzinfo=datetime.timezone.utc).astimezone(tz=None).strftime('%d.%m.%Y %H:%M:%S')
                    print(trade_time,price_buy_long,"BUY_LONG")

                    time.sleep(1)
                    limit_sell_price = (price_buy_long*trade_quantity + 0.2)/trade_quantity + price_buy_long * 0.002
                    timestamp = requests.get("https://api.binance.com/api/v3/time").json()
                    params = {'symbol': trade_symbol,'side': 'SELL','type': 'LIMIT','timeInForce': 'GTC','quantity': trade_quantity, 'price': round(limit_sell_price,tickSize),'recvWindow': 5000,'timestamp': timestamp['serverTime']}
                    query_string = urlencode(params)
                    params['signature'] = hmac.new(API_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
                    url = urljoin(BASE_URL, PATH)
                    r = requests.post(url, headers=headers, params=params)
                    if r.status_code == 200:
                        data = r.json()
                        print("Лимитный ордер выставлен успешно:","ORDER:", data["orderId"], "STATUS:", data["status"], "PRICE:", data["price"])
                        #send_telegram(trade_symbol + " SPOT ВХОД: " + str(price_buy_long) + " sUSDT: " + str(price_buy_long*trade_quantity) + " ВЫХОД: " + data["price"] + " PROFIT 0.2$")
                    else:
                        raise BinanceException(status_code=r.status_code, data=r.json())
                else:
                    raise BinanceException(status_code=r.status_code, data=r.json())

def on_error(ws, error):
    print("### error ###")
    print(error)
    time.sleep(5)
    binance_socket()

def on_close(ws):
    print("### closed ###")
    time.sleep(5)
    binance_socket()

def on_open(ws):
    print("### connected ###")

#if __name__ == "__main__":
def binance_socket():
    ws = websocket.WebSocketApp("wss://stream.binance.com:9443/ws/" + trade_symbol_low + "@kline_" + bar_interval,
                                on_message = on_message,
                                on_error = on_error,
                                on_close = on_close)
    ws.on_open = on_open
    ws.run_forever()

binance_socket()
