"""Торговый бот по идеям Билла Вильямса Торговый хаос 2. Дивергентный бар, Аллигатор, АО, определение ангуляции по Боллинджеру."""
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

# функция определяет есть ли пересечение бара с ma
def sma_crossing_bar(high,low,sma):
    if sma < high and sma >low:
        return True
    else:
        return False

#функция определяет находится ли бар внутри пасти аллигатора
def is_Candles_Far_from_Alligator(high, low, jaw, tooth, lip):
    
    min_alligator_value = min(jaw, tooth, lip)
    max_alligator_value = max(jaw, tooth, lip)
    
    if ((low > max_alligator_value and high > max_alligator_value)  or
        (high < min_alligator_value and low < min_alligator_value)):
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
        time.sleep(1) # Т.к. сообщения о закрытой свече могут прийти несколько раз подряд, делаем паузу (плохое решение нужно исправить)
        # получаем последние свечи для расчёта стратегии
        jsonKlines = requests.get("https://api.binance.com/api/v3/klines?symbol=" + trade_symbol + "&interval=" + bar_interval + "&limit=102").json()
        dfKlines = pd.DataFrame(jsonKlines, columns=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','buy_asset_volume','buy_quote_volume','ignore'])
        dfKlines = dfKlines.astype(float)
        # вычисляем среднюю цену баров
        dfAveragePrice = (dfKlines.high + dfKlines.low)/2
        # вычисляем аллигатора
        smma13 = dfAveragePrice.ewm(alpha=1/13, adjust=False).mean().shift(8) # зубы
        smma8 = dfAveragePrice.ewm(alpha=1/8, adjust=False).mean().shift(5) # челюсть
        smma5 = dfAveragePrice.ewm(alpha=1/5, adjust=False).mean().shift(3) # губы
        # вычисляем Awesome Oscillator
        sma5 = dfAveragePrice.rolling(window=5).mean()
        sma34 = dfAveragePrice.rolling(window=34).mean()
        ao = sma5 - sma34

        close_in_interval = 0 # иногда определение интервала не срабатывает. Чтобы небыло ошибки неизвестной переменной
        # определяем является ли бар дивергентным
        interval = (dfKlines.high.iloc[-2] - dfKlines.low.iloc[-2]) / 2

        if dfKlines.high.iloc[-2] > dfKlines.close.iloc[-2] and dfKlines.close.iloc[-2] > dfKlines.high.iloc[-2] - interval or dfKlines.high.iloc[-2] == dfKlines.close.iloc[-2]:
            close_in_interval = 1
        if dfKlines.close.iloc[-2] > dfKlines.low.iloc[-2] + interval and dfKlines.high.iloc[-2] - interval > dfKlines.close.iloc[-2]:
            close_in_interval = 2
        if dfKlines.close.iloc[-2] > dfKlines.low.iloc[-2] and dfKlines.low.iloc[-2] + interval > dfKlines.close.iloc[-2] or dfKlines.close.iloc[-2] == dfKlines.low.iloc[-2]:
            close_in_interval = 3
        # определяем "расстояние" между зубами и губами аллигатора
        alligator_dist = abs(smma13.iloc[-2]-smma5.iloc[-2])
        # определяем "расстояние" между максимальной ценой для бычьего бара и минимальной для медвежего бара
        bull_bar_dist = abs(dfKlines.high.iloc[-2]-smma5.iloc[-2])
        bear_bar_dist = abs(dfKlines.low.iloc[-2]-smma5.iloc[-2])
        # определяем бычий или медвежий тренд
        alligator_eat_up = True if smma5.iloc[-2] > smma8.iloc[-2] and smma5.iloc[-2] > smma13.iloc[-2] and smma8.iloc[-2] > smma13.iloc[-2] else False
        alligator_eat_down = True if smma5.iloc[-2] < smma8.iloc[-2] and smma5.iloc[-2] < smma13.iloc[-2] and smma8.iloc[-2] < smma13.iloc[-2] else False
        # проверяем не находится ли бар в пасти аллигатора
        bar_far_from_alligator = is_Candles_Far_from_Alligator(dfKlines.high.iloc[-2],dfKlines.low.iloc[-2],smma13.iloc[-2],smma8.iloc[-2],smma5.iloc[-2])
        # Боллинджер
        sma20 = dfAveragePrice.rolling(window=20).mean()
        bb_up = sma20 + dfKlines.close.rolling(window=20).std()*2
        bb_low = sma20 - dfKlines.close.rolling(window=20).std()*2
        # определяем "пробил" бар нижнюю линию Боллинджера
        bb_low_crossing_bar = sma_crossing_bar(dfKlines.high.iloc[-2],dfKlines.low.iloc[-2],bb_low.iloc[-2])
        # определяем "пробил" бар верхнюю линию Боллинджера
        bb_up_crossing_bar = sma_crossing_bar(dfKlines.high.iloc[-2],dfKlines.low.iloc[-2],bb_up.iloc[-2])

        # условие на покупку в лонг
        if (dfKlines.low.iloc[-3] > dfKlines.low.iloc[-2] and
            close_in_interval == 1 and
            ao.iloc[-3] > ao.iloc[-2] and
            ao.iloc[-2] < 0 and
            bull_bar_dist > alligator_dist and
            alligator_eat_down and
            bar_far_from_alligator and
            bb_low_crossing_bar):

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
