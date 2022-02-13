from os import getcwd, listdir, path
import os, io
import requests, zipfile
import datetime as dt
import time
import pandas as pd
import numpy as np
import mplfinance as mpf
import math
import json

# 1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w 1M

#symbols=['BTCUSDT','ETHUSDT','LTCUSDT','XRPUSDT','SOLUSDT','ADAUSDT','BNBUSDT','EOSUSDT','NEOUSDT']
symbols=['ATOMUSDT']
interval = '5m'
startTime = dt.datetime(2020,7,14)
endTime = dt.datetime(2020,7,16)

path_to_Data = path.join(getcwd(), 'Data')

def get_binance_bars(symbol, interval, startTime, endTime):
    url = "https://fapi.binance.com/fapi/v1/klines"
    #url = "https://api.binance.com/api/v3/klines"

    startTime = str(int(startTime.timestamp() * 1000))
    endTime = str(int(endTime.timestamp() * 1000))
    limit = '1000'

    req_params = {"symbol": symbol, 'interval': interval, 'startTime': startTime, 'endTime': endTime, 'limit': limit}

    data_arr = json.loads(requests.get(url, params=req_params).text)

    if (len(data_arr) == 0):
        return None

    return data_arr

def get_market_candles(symbol, interval, startTime, endTime):
    data_arr = []
    start_time = startTime
    print(symbol, 'is loading, wait...')
    while start_time <= endTime:
#         print(start_time)
        data = get_binance_bars(symbol, interval, start_time, endTime)
        time.sleep(0.2)

        if data is None:
            break

        data_arr.extend(data)

        t_delta = (data_arr[-1][0] / 1000) - (data_arr[-2][0] / 1000)
        start_time = dt.datetime.fromtimestamp((data_arr[-1][0] / 1000) + t_delta)

    return data_arr

def get_DataFrame(symbol, interval, startTime, endTime, path_to_Data):
    filename = f"{symbol}_{interval}_{startTime.strftime('%m-%d-%Y')}_{endTime.strftime('%m-%d-%Y')}.csv"

    if filename not in listdir(path_to_Data):
        data_arr = get_market_candles(symbol, interval, startTime, endTime)
        print('Num candles:', len(data_arr))

        ohlc_arr = np.array(list(map(lambda el: el[0:5], data_arr)), dtype=np.float64)

        ohlc_df = pd.DataFrame(ohlc_arr, columns=['datetime', 'open', 'high', 'low', 'close'])

        ohlc_df['datetime'] = pd.to_datetime(ohlc_df.datetime, unit='ms')
        ohlc_df.set_index(ohlc_df.datetime, inplace=True, drop=True)
        ohlc_df = ohlc_df[['open', 'high', 'low', 'close']]

        ohlc_df.to_csv(path.join(path_to_Data, filename))

    else:
        print(f'{filename} presence in Data => LOAD')

        ohlc_df = pd.read_csv(path.join(path_to_Data, filename))

        ohlc_df.set_index(pd.to_datetime(ohlc_df.datetime), inplace=True, drop=True)
        ohlc_df = ohlc_df[['open', 'high', 'low', 'close']]
        
        print('Num candles:', len(ohlc_df))

    return ohlc_df

def sma_crossing_bar(high,low,sma):
    if sma < high and sma >low:
        return True
    else:
        return False

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

for symbol in symbols:

    dfKlines = get_DataFrame(symbol, interval, startTime, endTime, path_to_Data)

    limit = len(dfKlines.index)

    dfAveragePrice = (dfKlines['high'] + dfKlines['low'])/2

    sma5 = dfAveragePrice.rolling(window=5).mean()
    sma34 = dfAveragePrice.rolling(window=34).mean()
    ao = sma5 - sma34
     
    #Боллинджер
    sma20 = dfAveragePrice.rolling(window=20).mean()
    bb_up = sma20 + dfKlines.close.rolling(window=20).std()*2
    bb_low = sma20 - dfKlines.close.rolling(window=20).std()*2

    #RSI
    dfRSI = get_RSI(dfKlines)

    sma_crossing_bar_index = 0
    sma20_crossing_bar_value = 0

    bull_bar = np.empty(limit)
    bear_bar = np.empty(limit)

    #Ищем бычий и медвежий дивергентный бар для входа в сделку.
    index = 0
    while index < len(dfKlines.index):
  
        #определяем "тип" бара
        if index >= 0 and index <= 1:
            bull_bar[index] = dfKlines.low[index]*0.999
            bear_bar[index] = dfKlines.high[index]*1.0

        if index > 1:
            interval = (dfKlines.high[index] - dfKlines.low[index]) / 2

            if dfKlines.high[index] > dfKlines.close[index] and dfKlines.close[index] > dfKlines.high[index] - interval or dfKlines.high[index] == dfKlines.close[index]:
                close_in_interval = 1
            if dfKlines.close[index] > dfKlines.low[index] + interval and dfKlines.high[index] - interval > dfKlines.close[index]:
                close_in_interval = 2
            if dfKlines.close[index] > dfKlines.low[index] and dfKlines.low[index] + interval > dfKlines.close[index] or dfKlines.close[index] == dfKlines.low[index]:
                close_in_interval = 3

            if dfKlines.low[index - 1] > dfKlines.low[index] and dfRSI[index] < 30 and close_in_interval == 1 and ao[index-1] > ao[index] and ao[index] < 0 and sma_crossing_bar(dfKlines.high[index],dfKlines.low[index],bb_low[index]):
                bull_bar[index] = dfKlines.low[index]*0.999
            else:
                bull_bar[index] = np.nan

            if dfKlines.high[index] > dfKlines.high[index - 1] and dfRSI[index] > 70 and close_in_interval == 3 and ao[index] > ao[index-1] and ao[index] > 0 and sma_crossing_bar(dfKlines.high[index],dfKlines.low[index],bb_up[index]):
                bear_bar[index] = dfKlines.high[index]*1.0
            else:
                bear_bar[index] = np.nan
        index +=1

    apdict = [  mpf.make_addplot(ao, panel=1, type='bar'),
                mpf.make_addplot(dfRSI, panel=2),
                mpf.make_addplot(bb_up, panel=0),
                mpf.make_addplot(bb_low, panel=0),
                mpf.make_addplot(bull_bar,panel=0,type='scatter',markersize=50,marker='d',color='g'),
                mpf.make_addplot(bear_bar,panel=0,type='scatter',markersize=50,marker='d',color='r'),
            ]

    # where data is a Pandas DataFrame object containing Open, High, Low and Close data, with a Pandas DatetimeIndex
    mpf.plot(dfKlines,addplot=apdict,title=symbol) #,type='candle'