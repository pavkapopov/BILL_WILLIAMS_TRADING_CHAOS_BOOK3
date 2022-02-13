"""Телеграм бот по 3 книге Билла Вильямса Торговый хаос 2"""
import json
import time
import datetime
import requests
import numpy as np
import websocket
import pandas as pd


trade_symbol = "1INCHUSDT" #торговая пара
trade_symbol_low = trade_symbol.lower() #торговая пара в нижнем регистре для передечи в websocket
bar_interval = "5m" #таймфрейм бара для анализа

# функция определяет пересекает MA бар
def sma_crossing_bar(high,low,ma):
    if ma < high and ma >low:
        return True
    else:
        return False

# функция отправки сообщения в Telegram
def send_telegram(text: str):
    token = ""
    url = "https://api.telegram.org/bot"
    channel_id = ""
    url += token
    method = url + "/sendMessage"

    r = requests.post(method, data={ "chat_id": channel_id, "text": text})

    if r.status_code != 200:
        print (r.status_code)
        raise Exception("post_text error")

def get_AROON(ohlc_df, lookback=25):
    
    if len(ohlc_df) < lookback:
        return [np.nan]*len(ohlc_df)
    
    aroon_up = 100 * ohlc_df.high.rolling(lookback + 1).apply(lambda x: x.argmax()) / lookback
    aroon_down = 100 * ohlc_df.low.rolling(lookback + 1).apply(lambda x: x.argmin()) / lookback
    
    return aroon_up, aroon_down

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

# основная функция, вызывается каждый раз когда в сокет приходит сообщение
def on_message(ws, message):
   
    trade = json.loads(message)

    if trade['e'] == "kline":
        is_this_kline_closed = trade['k']['x']

    if is_this_kline_closed:

        time.sleep(0.2)
        #опрееляем тренд по aroon, для торговли на тф 5м, рекомендуют определять тренд по тф 4ч
        jsonKlines_4h = requests.get("https://fapi.binance.com/fapi/v1/klines?symbol=" + trade_symbol + "&interval=4h&limit=102").json()
        dfKlines_4h = pd.DataFrame(jsonKlines_4h, columns=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','buy_asset_volume','buy_quote_volume','ignore'])
        dfKlines_4h = dfKlines_4h.astype(float)
        dfKlines_4h.set_index(keys=pd.to_datetime(dfKlines_4h['open_time'], unit='ms'), inplace=True)
        dfKlines_4h.drop(columns=['open_time','volume','close_time','quote_volume','trades','buy_asset_volume','buy_quote_volume','ignore'],inplace=True)

        # определяем тренд на тф 4 часа
        aroon_up_4h, aroon_down_4h = get_AROON(dfKlines_4h, 25)
        aroon_trend_up_4h = True if aroon_up_4h.iloc[-1] > 90 and aroon_down_4h.iloc[-1] < 30 else False
        aroon_trend_down_4h = True if aroon_down_4h.iloc[-1] > 90 and aroon_up_4h.iloc[-1] < 30 else False

        # получаем последние свечи для расчёта стратегии
        jsonKlines = requests.get("https://fapi.binance.com/fapi/v1/klines?symbol=" + trade_symbol + "&interval=" + bar_interval + "&limit=102").json()
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

                print(trade_symbol,"Выполнилось условие на покупку LONG!")
                send_telegram(trade_symbol + " ВХОД: " + str(dfKlines.close.iloc[-2]) + " LONG TP 2% / SL 2%")

        if (close_in_interval == 3
            and ao.iloc[-2] > ao.iloc[-3]
            and ao.iloc[-2] > 0
            and bb_up_crossing_bar
            and dfRSI_5m.iloc[-1] > 70
            and aroon_trend_down_4h):

                print(trade_symbol, "Выполнилось условие на покупку SHORT!")
                send_telegram(trade_symbol + " ВХОД: " + str(dfKlines.close.iloc[-2]) + " SHORT TP 2% / SL 2%")

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
    ws = websocket.WebSocketApp("wss://fstream.binance.com/ws/" + trade_symbol_low + "@kline_" + bar_interval,
                                on_message = on_message,
                                on_error = on_error,
                                on_close = on_close)
    ws.on_open = on_open
    ws.run_forever()

binance_socket()
