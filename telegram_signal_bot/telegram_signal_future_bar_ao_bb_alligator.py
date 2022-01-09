"""Торговый бот по 3 книге Билла Вильямса Торговый хаос 2"""
import json
import time
import datetime
import requests
import numpy as np
import websocket
import pandas as pd


trade_symbol = "BTCUSDT" #торговая пара
trade_symbol_low = trade_symbol.lower() #торговая пара в нижнем регистре для передечи в websocket
bar_interval = "5m" #таймфрейм бара для анализа

# функция определяет пересекает MA бар
def sma_crossing_bar(high,low,ma):
    if ma < high and ma >low:
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
    token = ""
    url = "https://api.telegram.org/bot"
    channel_id = "@trading_chaos_bw"
    url += token
    method = url + "/sendMessage"

    r = requests.post(method, data={ "chat_id": channel_id, "text": text})

    if r.status_code != 200:
        print (r.status_code)
        raise Exception("post_text error")

# основная функция, вызывается каждый раз когда в сокет приходит сообщение
def on_message(ws, message):
   
    trade = json.loads(message)

    if trade['e'] == "kline":
        is_this_kline_closed = trade['k']['x']

    if is_this_kline_closed:

        time.sleep(1)
        # получаем последние свечи для расчёта стратегии
        jsonKlines = requests.get("https://fapi.binance.com/fapi/v1/klines?symbol=" + trade_symbol + "&interval=" + bar_interval + "&limit=102").json()
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

                print(trade_symbol,"Выполнилось условие на покупку LONG!")
                send_telegram(trade_symbol + " ВХОД: " + str(dfKlines.close.iloc[-2]) + " LONG TP 2%")


        if (dfKlines.high.iloc[-2] > dfKlines.high.iloc[-3] and
            close_in_interval == 3 and
            ao.iloc[-2] > ao.iloc[-3] and
            ao.iloc[-2] > 0 and
            bear_bar_dist > alligator_dist and
            alligator_eat_up and
            bar_far_from_alligator and
            bb_up_crossing_bar):

                print(trade_symbol, "Выполнилось условие на покупку SHORT!")
                send_telegram(trade_symbol + " ВХОД: " + str(dfKlines.close.iloc[-2]) + " SHORT TP 2%")


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
