import os, io
import requests, zipfile
import datetime
import pandas as pd
import numpy as np
import mplfinance as mpf

# 1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w 1M

#symbols=['BTCUSDT','ETHUSDT','LTCUSDT','XRPUSDT','SOLUSDT','ADAUSDT','BNBUSDT','EOSUSDT','NEOUSDT']

symbols=['BTCUSDT']

for symbol in symbols:

    limit = 288
    jsonKlines = requests.get("https://api.binance.com/api/v3/klines?symbol=" + symbol + "&interval=3m&limit=" + str(limit)).json()
    dfKlines = pd.DataFrame(jsonKlines, columns=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','buy_asset_volume','buy_quote_volume','ignore'])
    dfKlines = dfKlines.astype(float)
    dfKlines.set_index(keys=pd.to_datetime(dfKlines['open_time'], unit='ms'), inplace=True)
    dfKlines.drop(columns=['open_time','close_time','quote_volume','trades','buy_asset_volume','buy_quote_volume','ignore'],inplace=True)

    dfAveragePrice = (dfKlines['high'] + dfKlines['low'])/2

    smma13 = dfAveragePrice.ewm(alpha=1/13, adjust=False).mean().shift(8) # зубы
    smma8 = dfAveragePrice.ewm(alpha=1/8, adjust=False).mean().shift(5) # челюсть
    smma5 = dfAveragePrice.ewm(alpha=1/5, adjust=False).mean().shift(3) # губы

    sma5 = dfAveragePrice.rolling(window=5).mean()
    sma34 = dfAveragePrice.rolling(window=34).mean()
    ao = sma5 - sma34
  
    #ищем фракталы
    fractal_signal_up_a = np.empty(limit)
    fractal_signal_down_a = np.empty(limit)

    bull_bar = np.empty(limit)
    bear_bar = np.empty(limit)

    #Ищем бычий и медвежий отклоняющийся бар и фракталы
    index = 0
    while index < len(dfKlines.index):
        #определяем "тип" бара
        if index >= 0 and index <= 1:
            bull_bar[index] = np.nan
            bear_bar[index] = np.nan

        if index > 1:
            interval = (dfKlines.high[index] - dfKlines.low[index]) / 2

            if dfKlines.high[index] > dfKlines.close[index] and dfKlines.close[index] > dfKlines.high[index] - interval or dfKlines.high[index] == dfKlines.close[index]:
                close_in_interval = 1
            if dfKlines.close[index] > dfKlines.low[index] + interval and dfKlines.high[index] - interval > dfKlines.close[index]:
                close_in_interval = 2
            if dfKlines.close[index] > dfKlines.low[index] and dfKlines.low[index] + interval > dfKlines.close[index] or dfKlines.close[index] == dfKlines.low[index]:
                close_in_interval = 3

            #dist1 = abs((dfKlines.high[index]+dfKlines.low[index])/2 - smma13[index])
            #dist2 = abs((dfKlines.high[index-10]+dfKlines.low[index-10])/2 - smma13[index-10])

            alligator_dist = abs(smma13[index]-smma5[index])
            #bull_bar_dist = ((dfKlines.high[index] + dfKlines.low[index])/2) - smma5[index] 
            bull_bar_dist = abs(dfKlines.high[index]-smma5[index])
            #bear_bar_dist = ((dfKlines.high[index] + dfKlines.low[index])/2) - smma5[index] 
            bear_bar_dist = abs(dfKlines.low[index]-smma5[index])
            alligator_eat_up = True if smma5[index] > smma8[index] and smma5[index] > smma13[index] and smma8[index] > smma13[index] else False
            alligator_eat_down = True if smma5[index] < smma8[index] and smma5[index] < smma13[index] and smma8[index] < smma13[index] else False

            if dfKlines.low[index - 1] > dfKlines.low[index] and  close_in_interval == 1 and ao[index-1] > ao[index] and ao[index] < 0 and bull_bar_dist > alligator_dist and alligator_eat_down:
                bull_bar[index] = dfKlines.low[index]*0.999
                print(smma13[index],smma5[index],alligator_dist,dfKlines.high[index],bull_bar_dist)
            else:
                bull_bar[index] = np.nan

            if dfKlines.high[index] > dfKlines.high[index - 1] and  close_in_interval == 3 and ao[index] > ao[index-1] and ao[index] > 0 and bear_bar_dist > alligator_dist and alligator_eat_up:
                bear_bar[index] = dfKlines.high[index]*1.0
            else:
                bear_bar[index] = np.nan

            if smma5[index] <= dfKlines.high[index] and smma5[index] >= dfKlines.low[index]:
                bull_bar[index] = np.nan
                bear_bar[index] = np.nan
            if smma8[index] <= dfKlines.high[index] and smma8[index] >= dfKlines.low[index]:
                bull_bar[index] = np.nan
                bear_bar[index] = np.nan
            if smma13[index] <= dfKlines.high[index] and smma13[index] >= dfKlines.low[index]:
                bull_bar[index] = np.nan
                bear_bar[index] = np.nan


    # определяем фракталы
        if index == 0 or index == 1:
            fractal_signal_up_a[index] = np.nan
            fractal_signal_down_a[index] = np.nan
        if index == limit - 2 or index == limit -1:
            fractal_signal_up_a[index] = np.nan
            fractal_signal_down_a[index] = np.nan
        if index >= 2 and index <= limit - 3:
            #Ищем фракталы вверх
            if dfKlines.high[index] > dfKlines.high[index-1] and dfKlines.high[index] > dfKlines.high[index-2] and dfKlines.high[index] > dfKlines.high[index+1] and dfKlines.high[index] > dfKlines.high[index+2]:
                fractal_signal_up_a[index] = dfKlines.high[index]*1.01
            else:
                fractal_signal_up_a[index] = np.nan
            #ищем фракталы вниз
            if dfKlines.low[index] < dfKlines.low[index-1] and dfKlines.low[index] < dfKlines.low[index-2] and dfKlines.low[index] < dfKlines.low[index+1] and dfKlines.low[index] < dfKlines.low[index+2]:
                fractal_signal_down_a[index] = dfKlines.low[index]*0.99
            else:
                fractal_signal_down_a[index] = np.nan
        index +=1

    apdict = [  mpf.make_addplot(ao, panel=1, type='bar'),
                #mpf.make_addplot(fractal_signal_up_a,panel=0,type='scatter',markersize=50,marker='^'),
                #mpf.make_addplot(fractal_signal_down_a,panel=0,type='scatter',markersize=50,marker="v"),
                mpf.make_addplot(bull_bar,panel=0,type='scatter',markersize=50,marker='d',color='g'),
                mpf.make_addplot(bear_bar,panel=0,type='scatter',markersize=50,marker='d',color='r'),
                mpf.make_addplot(smma5,panel=0,color='g',width=0.5),
                mpf.make_addplot(smma8,panel=0,color='r',width=0.5),
                mpf.make_addplot(smma13,panel=0,color='b',width=0.5),
            ]

    # where data is a Pandas DataFrame object containing Open, High, Low and Close data, with a Pandas DatetimeIndex
    mpf.plot(dfKlines,addplot=apdict,title=symbol) #,type='candle'