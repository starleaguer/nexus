#!/usr/bin/env python
# -*- coding: utf-8 -*-

from bs4 import BeautifulSoup as bs
from multiprocessing import Pool, Process, Manager
import multiprocessing
import tqdm
import requests
import json
import datetime
import time
import yaml
from pykrx import stock
import pandas as pd
import numpy as np
import FinanceDataReader as fdr
import os
import sys
import sqlite3
import traceback
from scipy.stats import linregress
import re
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import webbrowser

DELAY_SHORT = 0.1
DELAY_LONG = 10

DB_PATH = 'korea_stock.db'
STOCK_LIST_PATH = "_stocks.json"
BLACK_STOCK_LIST_PATH = "black_stocks.json"
KIS_DEV_PATH = 'kisdev_vi.yaml'

성장주_리스트 = []
저평가_리스트 = []

def save_list(my_list):
    now = datetime.datetime.now()
    path = now.strftime('%Y%m%d')+STOCK_LIST_PATH
    # with open(path, 'wb') as f:
    #     pickle.dump(my_list, f)
        
    with open(path, 'w') as f:
        json.dump(my_list, f)

def load_list():
    now = datetime.datetime.now()
    path = now.strftime('%Y%m%d')+STOCK_LIST_PATH
    if not os.path.exists(path):
        multiProcess()
        
    with open(path, 'r') as f:
        return json.load(f)

def add_black_list(code):
    with open(BLACK_STOCK_LIST_PATH, 'r') as f:
        data = json.load(f)

    if code not in data:
        data.append(code)
        with open(BLACK_STOCK_LIST_PATH, 'w') as f:
            json.dump(data, f)

        return True
    
    return False
    
def load_white_list():
    flag = False
    if not os.path.exists(BLACK_STOCK_LIST_PATH):
        return load_list()
        
    with open(BLACK_STOCK_LIST_PATH, 'r') as f:
        black = json.load(f)
    
    white = load_list()
        
    for x in black:
        if x in white:
            white.remove(x)
            flag = True
    
    if flag:
        save_list(white)
        
    return white


def get_stock_data(code, day):
    now = datetime.datetime.now()
    before = now - datetime.timedelta(days=day)
    try:
        df = fdr.DataReader(code, before.strftime('%Y%m%d'), now.strftime('%Y%m%d'))
        time.sleep(DELAY_SHORT)
        return df
    except:
        return pd.DataFrame()

# Indicators Function

def MA(df, n=20, column='Close'):
    """ 
    Function to calculate moving average
    ma_df = pd.DataFrame({'MA': ma})
    """

    ma = df[column].rolling(n).mean()
    ma_df = pd.DataFrame({'MA': ma})

    return ma_df


def EMA(df, n=20, column='Close'):
    """
    Function to calculate exponential moving average
    ema_df = pd.DataFrame({'EMA': ema})
    """
    alpha = 2 / (n + 1)
    ema = df[column].ewm(alpha=alpha, adjust=False).mean()
    ema_df = pd.DataFrame({'EMA': ema})

    return ema_df

def Stochastic(df, n=14, d=3):
    """
    Function to calculate Stochastic indicator
    stoch_df = pd.DataFrame({'K': k, 'D': d})
    """

    high_n = df['High'].rolling(n).max()
    low_n = df['Low'].rolling(n).min()

    k = 100 * ((df['Close'] - low_n) / (high_n - low_n))
    d = k.rolling(d).mean()
    stoch_df = pd.DataFrame({'K': k, 'D': d})

    return stoch_df


def MFI(df, n=14):
    """
    Function to calculate Money Flow Index
    mfi_df = MFI(df, 14)
    """

    tp = (df['High'] + df['Low'] + df['Close']) / 3
    mf = tp * df['Volume']
    pmf = mf.copy()
    pmf[df['Close'] <= df['Close'].shift(1)] = 0
    pmf = pmf.rolling(n).sum()
    nmf = mf.copy()
    nmf[df['Close'] >= df['Close'].shift(1)] = 0
    nmf = nmf.rolling(n).sum()
    mfr = pmf / nmf
    mfi_df = 100 - (100 / (1 + mfr))

    return pd.DataFrame({'MFI': mfi_df})


def RSI(df, n=14, column='Close'):
    """
    Function to calculate Relative Strength Index (RSI)
    rsi_df = RSI(df, 14)
    """

    delta = df[column].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(com=n, min_periods=n).mean()
    avg_loss = loss.ewm(com=n, min_periods=n).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi_df = pd.DataFrame({'RSI': rsi})

    return rsi_df

def StochRSI(df, period=14, ma_period=3):
    """
    Function to calculate StochRSI indicator
    stochrsi = pd.DataFrame({'K': k, 'D': d})
    """
    rsi = RSI(df, n=period)['RSI']
    min_rsi = rsi.rolling(window=period).min()
    max_rsi = rsi.rolling(window=period).max()
    k = (rsi - min_rsi) / (max_rsi - min_rsi)
    d = k.rolling(window=ma_period).mean()
    stochrsi = pd.DataFrame({'K': k, 'D': d})
    return stochrsi

def MACD(df, n_fast=12, n_slow=26, n_signal=9, column='Close'):
    """
    Function to calculate the MACD and signal line indicators
    macd_df = MACD(df, 12, 26, 9)
    """
    ema_fast = df[column].ewm(span=n_fast, min_periods=n_fast).mean()
    ema_slow = df[column].ewm(span=n_slow, min_periods=n_slow).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=n_signal, min_periods=n_signal).mean()
    macd_df = pd.DataFrame({'MACD': macd, 'Signal': signal})

    return macd_df


def Bollinger_bands(df, n=20, k=2):
    """
    Function to calculate Bollinger Bands
    bb_df = pd.DataFrame({'Upper': upper_band, 'Mid': sma, 'Lower': lower_band})
    """

    sma = df['Close'].rolling(n).mean()
    std = df['Close'].rolling(n).std()
    upper_band = sma + k * std
    lower_band = sma - k * std
    bb_df = pd.DataFrame({'Upper': upper_band, 'Mid': sma, 'Lower': lower_band})

    return bb_df


def get_low_price(df, n=5, p=10):
    # 일별 종가를 기준으로 rolling minimum 계산
    df['rolling_min'] = df['Close'].rolling(window=n, min_periods=1).min()

    # 저점인지 아닌지 여부를 나타내는 boolean 컬럼 추가
    df['is_bottom'] = df['Close'] == df['rolling_min']

    bottoms = df[df['is_bottom']]
    ma = df['Close'].rolling(20).mean()

    smaller_than_average = bottoms[bottoms['Close'] < ma.iloc[-1]]
    average= np.mean(smaller_than_average['Close'])
    nearest = smaller_than_average.iloc[(smaller_than_average['Close'] - average).abs().argsort()[:1]]

    # 추세선을 위한 데이터프레임 생성
    trendline_data = pd.DataFrame({'Date': smaller_than_average.index, 'Close': smaller_than_average['Close']})

    # Date 컬럼을 datetime 형식으로 변환
    trendline_data['Date'] = pd.to_datetime(trendline_data['Date'])

    # 추세선 계산을 위한 x, y 값 추출
    x = np.array(range(len(trendline_data)))
    y = np.array(trendline_data['Close'])
    z = np.polyfit(x, y, 1)

    # 추세선 계산
    # print("Slope:", z[0])
    # print("Intercept:", z[1]) 

    # 현재 날짜에서의 추세선 계산
    trendline_today = z[0] * len(smaller_than_average) + z[1]

    # print(f"추세선: {trendline_today:.2f} 입니다.")
    # print(f"평균값: {nearest['Close'].iloc[0]:.2f} 입니다.")
    # print(f"현재가격: {df['Close'].iloc[-1]:.2f} 입니다.")
    
    가격평 = abs(df['Close'].iloc[-1] - nearest['Close'].iloc[0]) * 100 / df['Close'].iloc[-1]
    가격추 = abs(df['Close'].iloc[-1] - trendline_today) * 100 / df['Close'].iloc[-1]
    
    return (가격평+가격추, trendline_today)
    if (가격평+가격추 < p) and df['Close'].iloc[-1] >= trendline_today :
        return True
    
    else:
        return False
    
def Volume_profile(df, n=60):
    time.sleep(DELAY_SHORT)

    data = df.tail(n)
    price_stack = {}
    sum_volum = 0
    for idx, row in data.iterrows():
        if row['Close'] < 2000:
            r = 10
        elif row['Close'] < 20000:
            r = 100
        elif row['Close'] < 200000:
            r = 1000
        else:
            r = 10000
              
        close = str(round(row['Close'] /r))
        if close in price_stack:
            price_stack[close] += row['Volume']
        else:
            price_stack[close] = row['Volume']
        sum_volum += row['Volume']

        now = row['Close']
    
    try:
        if sum_volum == 0:
            return 0
            
        for key, val in price_stack.items():
            price_stack[key] = round(val*100/sum_volum,2)
        
        sorted_data = sorted(price_stack.items(), key=lambda x: x[0], reverse=True)
        # print(sorted_data)

        res = 0
    
        for i in sorted_data:
            p = int(i[0])*r
            if now >= p:
                res += i[1]

        return round(res)
    
    except:
        return False


def Ratio_profile(df, n=0, ratio=3):
    if n == 0:
        data = df
    else:
        data = df.tail(n)
    
    now_price = data['Close'].iloc[-1]
    price_stack = {}
    sum_volum = 0
    for idx, row in data.iterrows():             
        close = row['Close']
        if close in price_stack:
            price_stack[close] += row['Volume']
        else:
            price_stack[close] = row['Volume']
        sum_volum += row['Volume']
    
    try:
        for key, val in price_stack.items():
            price_stack[key] = round(val*100/sum_volum,2)     
        
        sorted_data = sorted(price_stack.items())
        start_key, end_key = sorted_data[0][0], sorted_data[-1][0]

        n = 20
        step = (end_key - start_key) / (n - 1)
        new_data = {}
        for i in range(n):
            key = int(start_key + i * step)
            values_sum = 0
            count = 0
            for k, v in sorted_data:
                if key - step/2 <= k <= key + step/2:
                    values_sum += v
                    count += 1
                    
            if count > 0:
                new_data[key] = round(values_sum, 2)
                
        data = dict(sorted(new_data.items(), key=lambda item: item[1], reverse=True))

        closest_value = []
        high_value = []
        for i in range(10,100,10):
            for key, value in data.items():
                if len(closest_value) >= 2 and len(high_value) >= 2:
                    break
                
                if now_price*(1-(i/100)) <= key*(1-((i-10)/100)) and key*(1+((i-10)/100)) <= now_price*(1+(i/100)) and value > 5:
                    if now_price > key and len(closest_value) <= 1:
                        closest_value.append([key, value, round((key-now_price)*100/now_price, 2)])
                    elif now_price < key and len(high_value) <= 1:
                        high_value.append([key, value, round((key-now_price)*100/now_price, 2)])
                    else:
                        pass
          
        if len(high_value) > 0 and len(closest_value) > 0:
            profit = round(high_value[0][2] + closest_value[0][2]*1.5, 2)        
            data = {"저항": high_value[0][0], "지지":closest_value[0][0], "손익비":profit}
            
            if profit > ratio:
                return True
        return False
        
    except:
        return False

class KIS:
    def __init__(self):
        self._cfg = self._load_cfg()
        self.headers = self.set_header()
        # {'상품번호': i['pdno'], '주문수량': i['ord_qty'], '주문단가': i['ord_unpr'], '매도매수': i['sll_buy_dvsn_cd']}
        self.order_list = {}
        self.code = ""
        self.order_done = {}
        self.order_info = {}

    @staticmethod
    def qty_check(qty):
        if (qty is float) or (qty is int):
            qty = int(qty)

        return str(qty)

    @staticmethod
    def _load_cfg():
        with open(KIS_DEV_PATH, encoding='UTF-8') as f:
            _cfg = yaml.load(f, Loader=yaml.FullLoader)
        return _cfg

    @staticmethod
    def price_check(price):
        if (price is str) or price is float:
            price = int(float(price))
        if price < 1000:
            hoga = 1
        elif price < 5000:
            hoga = 5
        elif price < 10000:
            hoga = 10
        elif price < 50000:
            hoga = 50
        elif price < 100000:
            hoga = 100
        elif price < 500000:
            hoga = 500
        else:
            hoga = 1000
        return str(int(price - (price % hoga)))

    def set_code(self, code):
        self.code = code
        return code

    def get_code_name(self):
        with open('stock_code.json') as file:
            codes = json.load(file)
        return [k for k, v in codes.items() if v == self.code]

    def set_header(self):
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self._cfg['ACCESS_TOKEN']}",
            "appKey": self._cfg['APP_KEY'],
            "appSecret": self._cfg['APP_SECRET']
        }
        return headers

    def error_code(self, res):
        if res['rt_cd'] == '1' and res['msg_cd'] == 'EGW00123':
            self.접근토큰발급()
        elif res['rt_cd'] == '1' and res['msg_cd'] == 'EGW00201':
            time.sleep(DELAY_LONG)
        else:
            self.send_message(title='[주문 실패]', msg=f'{str(res)}')
        return False

    def order_check(self):
        for j in self.order_list:
            if self.order_list[j]['상품번호'] == self.code:
                return True
        return False

    def send_message(self, title='', msg='', content=''):
        """디스코드 메시지 전송"""
        data = {
            "content" : content,
            "username" : "kis.py"
        }
        if msg != '':
            data["embeds"] = [
                {
                    "description" : msg,
                    "title" : title
                }
            ]
            
        requests.post(self._cfg['DISCORD_WEBHOOK_URL'], json=data)

    def kis_api(self, method, path, headers, data):
        path_blist = ['/uapi/domestic-stock/v1/trading/inquire-balance', '/uapi/domestic-stock/v1/quotations/inquire-price']
        if path not in path_blist:
            print('request', method, path)

        url = self._cfg['URL_BASE'] + path

        if method == 'post':
            res = requests.post(url, headers=headers, data=json.dumps(data))
        else:
            res = requests.get(url, headers=headers, params=data)
        return res

    def 접근토큰발급(self):
        headers = {"content-type": "application/json"}
        body = {"grant_type": "client_credentials",
                "appkey": self._cfg['APP_KEY'],
                "appsecret": self._cfg['APP_SECRET']}
        path = "/oauth2/tokenP"
        res = self.kis_api(method='post', path=path, headers=headers, data=body)
        # res = requests.post(url, headers=headers, data=json.dumps(body))

        self._cfg['ACCESS_TOKEN'] = res.json()["access_token"]
        with open(KIS_DEV_PATH, 'w') as f:
            yaml.safe_dump(self._cfg, f)
        self.headers = self.set_header()

    def 보유현금조회(self):
        path = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        self.headers["tr_id"] = "TTTC8908R"
        self.headers["custtype"] = "P"
    
        params = {
            "CANO": self._cfg['CANO'],                   # 계좌 앞 8자리
            "ACNT_PRDT_CD": self._cfg['ACNT_PRDT_CD'],   # 계좌 뒤 2자리
            "PDNO": "005930",               # 상품번호 (현재는 삼성전자)
            "ORD_UNPR": "00054500",         # 주문단가
            "ORD_DVSN": "00",               # 주문구분
            "CMA_EVLU_AMT_ICLD_YN": "N",    # CMA평가금액 포함여부
            "OVRS_ICLD_YN": "N",            # 해외포함여부
        }
    
        res = self.kis_api(method='get', path=path, headers=self.headers, data=params)
        # res = requests.get(url, headers=self.headers, params=params)
    
        if res.json()['rt_cd'] == '0':
            balance = int(res.json()['output']['ord_psbl_cash'])
            # self.send_message(f"주문 가능 현금 잔고: {balance}원")
            return int(balance)
        else:
            return self.error_code(res.json())

    def 현재시세(self):
        time.sleep(DELAY_SHORT)
        path = "/uapi/domestic-stock/v1/quotations/inquire-price"

        self.headers["tr_id"] = "FHKST01010100"          # 거래 ID - FHKST01010100 : 주식 현재가
        params = {
            "fid_cond_mrkt_div_code": "J",               # FID 조건 시장 분류 코드 : J(주식, ETF, ETN)
            "fid_input_iscd": self.code,                      # FID 입력 종목코드 : 종목번호 6자리
        }
        res = self.kis_api(method='get', path=path, headers=self.headers, data=params)
        # res = requests.get(url, headers=self.headers, params=params)

        if res.json()['rt_cd'] == '0':
            return res.json()['output']
        else:
            return self.error_code(res.json())

    # def 현재호가(self):
    #     path = "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
    #
    #     self.headers["tr_id"] = "FHKST01010200"          # 거래 ID - FHKST01010200 : 주식현재가 호가 예상체결
    #     # Query Parameter
    #     params = {
    #         "fid_cond_mrkt_div_code": "J",               # FID 조건 시장 분류 코드 : J(주식, ETF, ETN)
    #         "fid_input_iscd": self.code,                      # FID 입력 종목코드 : 종목번호 6자리
    #     }
    #
    #     res = self.kis_api(method='get', path=path, headers=self.headers, data=params)
    #     # res = requests.get(url, headers=self.headers, params=params)
    #
    #     if res.json()['rt_cd'] == '0':
    #         return res.json()['output1']
    #     else:
    #         return self.error_code(res.json())

    def 주식주문(self, order, qty, price, market="00"):
        
        if self.order_check():
            return False
        
        have_money = self.보유현금조회()
        
        if have_money < price*qty:
            return False
               
        price = self.price_check(price)
        qty = self.qty_check(qty)

        if order == '매수':
            self.headers["tr_id"] = "TTTC0802U"  # 매수주문 실전 TTTC0802U(실전) / 매도주문 TTTC0801U
            qty = str(round(100000/int(price))) 
        elif order == '매도':
            self.headers["tr_id"] = "TTTC0801U"  # 매수주문 실전 TTTC0802U(실전) / 매도주문 TTTC0801U
        else:
            return False

        self.headers["custtype"] = "P"

        path = "/uapi/domestic-stock/v1/trading/order-cash"

        data = {
          "CANO": self._cfg['CANO'],
          "ACNT_PRDT_CD": self._cfg['ACNT_PRDT_CD'],
          "PDNO": self.code,     # 종목 번호
          "ORD_DVSN": market,     # 주문 구분 00(지정가) 01(시장가)
          "ORD_QTY": qty,      # 주문 수량
          "ORD_UNPR": price,      # 주문 단가 : 1주당 가격 * 장전 시간외, 장후 시간외, 시장가의 경우 1주당 가격을 공란으로 비우지 않음 "0"으로 입력 권고
        }

        res = self.kis_api(method='post', path=path, headers=self.headers, data=data)
        # res = requests.post(url, headers=self.headers, data=json.dumps(data))
        if res.json()['rt_cd'] == '0':
            self.send_message(title =f'[주식{order}]', msg=f'{self.get_code_name()} / {price} / {qty}')
            self.set_order_done()
            return True
        else:
            return self.error_code(res.json())

    def 주식미체결(self):
        path = "/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl"

        self.headers["tr_id"] = "TTTC8036R"  # 거래 ID - FHKST01010200 : 주식현재가 호가 예상체결
        # Query Parameter
        params = {
            "CANO": self._cfg['CANO'],           # 계좌번호 체계(8-2)의 앞 8자리 (8)
            "ACNT_PRDT_CD": self._cfg['ACNT_PRDT_CD'],
            "CTX_AREA_FK100": "",   #
            "CTX_AREA_NK100": "",   #
            "INQR_DVSN_1": "0",     # 0:조회순 1:주문순 2:종목순
            "INQR_DVSN_2": "0",     # 0:전체 1:매도 2:매수
        }
        res = self.kis_api(method='get', path=path, headers=self.headers, data=params)
        # res = requests.get(url, headers=self.headers, params=params)

        if res.json()['rt_cd'] == '0':
            self.order_list = {}
            for i in res.json()['output']:
                self.order_list[i['odno']] = {'상품번호': i['pdno'], '주문수량': i['ord_qty'], '주문단가': i['ord_unpr'], '매도매수': i['sll_buy_dvsn_cd']}
            return True
        else:
            return self.error_code(res.json())

    # def 예약확인(self):
    #     path = "/uapi/domestic-stock/v1/trading/order-resv-ccnl"
    #
    #     self.headers["tr_id"] = "CTSC0004R"  # 거래 ID - FHKST01010200 : 주식현재가 호가 예상체결
    #
    #     params = {
    #         "RSVN_ORD_ORD_DT": "J",         # 예약주문시작일자 (8)
    #         "RSVN_ORD_END_DT": "",          # 예약주문종료일자 (8)
    #         "TMNL_MDIA_KIND_CD": "00",      # 단말매체종류코드
    #         "CANO": self._cfg['CANO'],                   # 종합계좌번호
    #         "ACNT_PRDT_CD": self._cfg['ACNT_PRDT_CD'],   # 계좌번호 체계(8-2)의 뒤 2자리
    #         "PRCS_DVSN_CD": "0",            # 처리구분코드
    #         "CNCL_YN": "Y",                 # 취소여부
    #     }
    #
    #     res = self.kis_api(method='get', path=path, headers=self.headers, data=params)
    #     # res = requests.get(url, headers=self.headers, params=params)
    #
    #     if res.json()['rt_cd'] == '0':
    #         return res.json()['output']
    #     else:
    #         return self.error_code(res.json())

    def 주식기간별시세(self, day):
        path = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"

        now = datetime.datetime.now()
        before = now - datetime.timedelta(days=day)

        self.headers["tr_id"] = "FHKST03010100"

        data = {
          "FID_COND_MRKT_DIV_CODE": "J",
          "FID_INPUT_ISCD": self.code,
          "FID_INPUT_DATE_1": before.strftime('%Y%m%d'),     # 조회 시작일자 (ex. 20220501)
          "FID_INPUT_DATE_2": now.strftime('%Y%m%d'),     # 조회 종료일자 (ex. 20220530)
          "FID_PERIOD_DIV_CODE": "D",     # D:일봉, W:주봉, M:월봉, Y:년봉
          "FID_ORG_ADJ_PRC": "0"         # 0:수정주가 1:원주가
        }

        res = self.kis_api(method='get', path=path, headers=self.headers, data=data)
        # res = requests.get(url, headers=self.headers, params=data).json()

        if res.json()['rt_cd'] == '0':
            return res.json()
        else:
            return self.error_code(res.json())

    def 주식잔고조회(self):
        path = "/uapi/domestic-stock/v1/trading/inquire-balance"

        self.headers["tr_id"] = "TTTC8434R"  # 매수주문 실전 TTTC0802U(실전) / 매도주문 TTTC0801U

        data = {
            "CANO": self._cfg['CANO'],
            "ACNT_PRDT_CD": self._cfg['ACNT_PRDT_CD'],
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "N",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }

        res = self.kis_api(method='get', path=path, headers=self.headers, data=data)
        # res = requests.get(url, headers=self.headers, params=data)
        if res.json()['rt_cd'] == '0':
            return res.json()['output1']
        else:
            return self.error_code(res.json())

    def 주식주문체결조회(self):
        path = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"

        self.headers["tr_id"] = "TTTC8001R"  # 매수주문 실전 TTTC0802U(실전) / 매도주문 TTTC0801U

        now = datetime.datetime.now()
        date = now.strftime('%Y%m%d')
        
        data = {
            "CANO": self._cfg['CANO'],
            "ACNT_PRDT_CD": self._cfg['ACNT_PRDT_CD'],
            "INQR_STRT_DT": date,
            "INQR_END_DT": date,
            "SLL_BUY_DVSN_CD": "02",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "01",  
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "00",
        }

        res = self.kis_api(method='get', path=path, headers=self.headers, data=data)
        # res = requests.get(url, headers=self.headers, params=data)
        if res.json()['rt_cd'] == '0':
            return res.json()['output1']
        else:
            return self.error_code(res.json())

    def check_order_done(self):
        now = datetime.datetime.now()
        date = now.strftime('%Y%m%d')
        
        for i in self.order_done:
            if date == self.order_done[i]['buy_date'] and i == self.code:
                return True
        
        output = self.주식주문체결조회()
        for i in output:
            if i['sll_buy_dvsn_cd'] == "02" and i['pdno'] == self.code:
                return True
        return False

    def set_order_done(self):
        now = datetime.datetime.now()
        date = now.strftime('%Y%m%d')
        self.order_done[self.code] = {'buy_date': date}

    # 전략
    def 저평가_전략(self):
        buy_flag = False
        
        low_stock_list = load_white_list()

        for code in low_stock_list:
            self.set_code(code)
            
            if self.order_check():
                continue
                
            output = self.현재시세()
            if output != 0:
                now_price = int(output['stck_prpr'])
                if code in self.order_info:
                    if self.order_info[code]['매수가격'] > now_price and self.order_info[code]['주문가능'] == False:
                        self.order_info[code]['주문가능'] = True
                
                    if self.order_info[code]['매수가격'] < now_price and self.order_info[code]['주문가능'] == True:
                        price = int(output['stck_prpr']) + int(output['aspr_unit'])
                        qty = round(100000 / price) 
                        if self.주식주문(order='매수', qty=qty, price=price):
                            self.order_info[code]['주문가능'] = False
                            buy_flag = True

        return buy_flag

    def calculate_volatility(self, symbol, days):
        bars = api.get_barset(symbol, 'day', limit=days)
        prices = [bar.c for bar in bars[symbol]]
        log_returns = np.log(prices) - np.log(prices[:-1])
        volatility = np.std(log_returns) / np.mean(log_returns)
        return volatility

    # 전략
    def 유동성공급_전략(self):
        buy_flag = False

        low_stock_list = ['105560', '005930', '030200']
        for code in low_stock_list:
            self.set_code(code)
            
            if self.order_check():
                continue
                
            output = self.현재시세()
            
            if output != 0:
                now_price = int(output['stck_prpr'])
                w52_lwpr = int(output['w52_lwpr'])
                w52_hgpr = int(output['w52_hgpr'])
                
                w52_hoga = (w52_hgpr - w52_lwpr) / 20
                
                print(now_price, w52_lwpr, w52_hgpr, w52_hoga)
                
                # if 주식비중이 50% 이하라면 매도 중지
                # if 주식비중이 100% 이상이라면 매수중지
                
                # if code in self.order_info:
                #     if self.order_info[code]['매수가격'] > now_price and self.order_info[code]['주문가능'] == False:
                #         self.order_info[code]['주문가능'] = True
                
                #     if self.order_info[code]['매수가격'] < now_price and self.order_info[code]['주문가능'] == True:
                #         price = int(output['stck_prpr']) + int(output['aspr_unit'])
                #         qty = round(100000 / price) 
                #         if self.주식주문(order='매수', qty=qty, price=price):
                #             self.order_info[code]['주문가능'] = False
                #             buy_flag = True

        return buy_flag
    
    def 익절손절(self, per, profit):
        """per=수익률, profit=수익금"""

        data = self.주식잔고조회()
        if data is not False:
            for i in data:
                
                # 익절
                if int((i['evlu_pfls_amt'])) > profit or float(i['evlu_pfls_rt']) > per:
                    code = self.set_code(i['pdno'])
                    output = self.현재시세()
                    if output != 0:
                        now_price = int(output['stck_prpr'])
                        if self.order_info[code]['매도가격'] < now_price and self.order_info[code]['주문가능'] == False:
                            self.order_info[code]['주문가능'] = True
                            
                        if self.order_info[code]['매도가격'] < now_price and self.order_info[code]['주문가능'] == True:
                            self.order_info[code]['주문가능'] = False
                            self.주식주문(order='매도', qty=i['hldg_qty'], price=i['prpr'], market="01")  # market=01 시장가

                # 손절
                # if float(i['evlu_pfls_rt']) < -4:
                #     code = self.set_code(i['pdno'])
                #     if self.order_info[code]['손절가격'] > now_price:
                #         self.주식주문(order='매도', qty=i['hldg_qty'], price=i['prpr'], market="01")  # market=01 시장가
                #         print('손절')
                    
    
    
    
    def strategy(self):
        if self.유동성공급_전략():
            self.주식미체결()
            
        # if self.저평가_전략():
        #     self.주식미체결()
        
        # self.익절손절(per=5, profit=10000)
        
        
    def send_trading_stock_info(self):
        # 거래 종목 불러오기
        저평가_리스트 = load_white_list()

        my_dict = {}
        tmp = []
        for i in 저평가_리스트:
            d = " "            
            업종 = q_db('''SELECT value FROM '%s' WHERE name='%s' ''' % (i, "업종"))
            if len(업종) > 0:
                d = 업종[0][0].replace("FICS  ","")
            my_dict[i] = d
            
        sorted_dict = dict(sorted(my_dict.items(), key=lambda x: (-list(my_dict.values()).count(x[1]), str(x[1]))))

        for i in sorted_dict:
            text = get_stock_headline(i)
            name = stock.get_market_ticker_name(i)
            data = single_annual(i)
            str_msg = ''
            if data[0]:
                str_msg = '매수:{}({}%), 매도:{}, 연:{}%'.format(data[1]['매수가격'], data[1]['매수가격차이'], data[1]['매도가격'], data[1]['연환산수익률'])
                data[1]['주문가능'] = False
                self.order_info[i] = data[1]
                
            msg = f'#{name} | {sorted_dict[i]}\n "{text}"\n {str_msg}\n\n'
            tmp.append(msg)
                        
            if len(tmp) > 20:
                list_string = ''.join(map(str, tmp))
                self.send_message(content=list_string)
                tmp = []
        
        list_string = ''.join(map(str, tmp))
        self.send_message(title='트레이딩 종목 리스트', msg='종목 수:'+str(len(sorted_dict)), content=list_string)

    def run(self):
        # self.send_trading_stock_info()
        # self.주식미체결()
        start_flag = False
                
        while True:
            now = datetime.datetime.now()
            t_open = now.replace(hour=9, minute=0, second=0,microsecond=0)
            t_exit = now.replace(hour=15, minute=15, second=0,microsecond=0)
            today = datetime.datetime.today().weekday()
            
            if t_open <= now and now <= t_exit and today <= 4:
                if not start_flag:
                    start_flag = True
                    self.send_message(title= 'kis.py', msg="자동 매매 시작")
                    
                self.strategy() # 메인 실행문
                time.sleep(DELAY_LONG)
                
            # elif now > t_exit or today > 4:
            #     start_flag = False
            #     if today == 4: 
            #         days = 3
            #     elif today == 5:
            #         days = 2
            #     else:
            #         days = 1
                
            #     tomorrow_nine = datetime.datetime.combine(datetime.date.today() + datetime.timedelta(days=days), datetime.time(hour=8, minute=58))
            #     self.send_message(title= 'kis.py', msg="다음날 오전 9시까지 대기")
            #     while datetime.datetime.now() < tomorrow_nine:
            #         time_to_wait = (tomorrow_nine - datetime.datetime.now()).total_seconds()
            #         time.sleep(time_to_wait)
            #     self.send_trading_stock_info()
                
            # elif now < t_open:
            #     start_flag = False
            #     self.send_message(title= 'kis.py', msg="오전 9시까지 대기")
            #     tomorrow_nine = datetime.datetime.combine(datetime.date.today() + datetime.timedelta(days=0), datetime.time(hour=8, minute=58))
            #     while datetime.datetime.now() < tomorrow_nine:
            #         time_to_wait = (tomorrow_nine - datetime.datetime.now()).total_seconds()
            #         time.sleep(time_to_wait)
            #     self.send_trading_stock_info()
                
            # else:
            #     start_flag = False
            #     self.send_message(title= 'kis.py', msg="30초 대기")
            #     time.sleep(30)
                

def sungjang(value_list):
    if len(value_list) < 2:
        return 0

    if type(value_list[0]) is str:
        tmp_list = []
        for i in value_list:
            if i != "" and i != "None":
                try:
                    tmp_list.append(float(i.replace(",", "")))
                except:
                    pass
        value_list = tmp_list

    if len(value_list) < 2:
        return 0

    res_list = []
    for i in range(1, len(value_list)):
        if value_list[i-1] != 0:
            tmp = (value_list[i] - value_list[i-1]) / abs(value_list[i-1])
            if tmp < 0:
                res_list.append(tmp * 1.5)
            else:
                res_list.append(tmp)

    if len(res_list) >= 1:
        res_list.append(res_list[-1])
        return round(sum(res_list)/len(res_list), 4)
    else:
        return 0
    
def q_db(q):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(q)
    rows = cur.fetchall()
    conn.close()
    return rows

def get_finance_info(code='005930', condition='매출액', n=5):
    try:
        now = datetime.datetime.now()
        year = now.year
        data = {}

        results = []
        for y in range(year-n, year+1):
            result = q_db('''SELECT value FROM "%s" WHERE name='%s' AND year='%s' ''' % (code, condition, y))
            if len(result) > 0:
                results.append(result[0][0])
        
        if len(results) > 1:
            data[condition] = [float(results[-1].replace(",", "")), sungjang(results)]
        else:
            data[condition] = [float(results[0].replace(",", "")), 0]

        return data
    except:
        data[condition] = [0, 0]
        return data


def 정보검사(code, negative):
    res = get_stock_headline(code)
    # negative = ['부진', '악화', '감소', '축소', '적자', '부담', '침체', '급감', '하회', '약화']
    for i in negative:
        if i in res:
            return False
    
    return True

def 재무재표검사(code, conds):

    low_value = ['PBR', 'PER', '부채비율']
    
    for c in conds:
        data = get_finance_info(code, c, 5)
        
        if c in data:
            if c in low_value:
                if data[c][0] > conds[c][0]:
                    return False
                
            elif c =='발행주식수':
                if data[c][1] > 0:
                     return False
            
            elif data[c][0] < conds[c][0] or data[c][1] < conds[c][1]:
                return False
    return True


def 경쟁사비교(code, rank=3):
    try:
        url = 'http://comp.fnguide.com/SVO2/ASP/SVD_Comparison.asp?pGB=1&gicode=A'+ code +'&cID=&MenuYn=Y&ReportGB=&NewMenuID=106&stkGb=701&cpGb=undefined'

        response = requests.get(url)
        html_content = response.content

        soup = bs(html_content, "html.parser")
        table = soup.find(id="grid_D_Y")
        table_body = table.find("tbody")

        data = {}
        avg_data = {}
        for row in table_body.find_all("tr"):
            th = row.find_all("th")[0].text.strip()
            cols = row.find_all("td")
            tmp = []
            for c in cols:
                if th == 'PBR':
                    c = c.text.strip().replace(',', '').replace('N/A', '2')
                elif th =='PER':
                    c = c.text.strip().replace(',', '').replace('N/A', '15')
                elif th =='ROE':
                    c = c.text.strip().replace(',', '').replace('N/A', '10')
                else:
                    c = c.text.strip().replace(',', '').replace('흑전', '0').replace('적지', '0').replace('N/A', '0').replace('적전', '0').replace('Tag', '0')
                tmp.append(c)

            if len(tmp) > 2:
                data[th] = tmp
                avg_data[th] = 0
        
        markey_div_not_list = ['PER', 'PBR', 'ROE', '영업이익률', '매출액증가율',]
        low_win_list = ['PER', 'PBR']
        confirm_list = ['자산총계', '자본총계', '순영업손익', 'PER', 'PBR', 'ROE', '영업이익률', '매출액증가율']
        count = len(data['시가총액'])
        res = {}
        for key in avg_data:
            if key not in confirm_list:
                continue
            wins = 1
            for i in range(1, count):
                if key in markey_div_not_list:
                    zero = float(data[key][0])
                    another = float(data[key][i])
                else:
                    zero = float(data[key][0]) / float(data['시가총액'][0])
                    another = float(data[key][i]) / float(data['시가총액'][i])
                    
                if key in low_win_list:
                    if zero >= another:
                        wins += 1
                else:
                    if zero <= another:
                        wins += 1
            
            res[key]= wins
        
        avg_rank = 0
        for i in res:
            avg_rank += res[i] 
        
        if avg_rank/len(res) > rank:
            return False
        
        return True
    
    except:
        return False

def 차트검사(code):
    
    # if not chart_filter_low_price(code):
    #     return False

    if not chart_filter_rsi_longterm(code):
        return False
    
    if not chart_filter_volume_uptrend(code):
        return False

    if not multi_annual(code):
        return False
    
    return True

def chart_filter_rsi_longterm(code):
    data = get_stock_data(code, 600)
    if data.empty:
        return False
    
    price_count = data[['Close']].notnull().all(axis=1).sum()
    if price_count < 240:
        return False
    
    rsi = RSI(df=data, n=240, column='Close')
    rsi_ma120 = MA(rsi, n=120, column='RSI')
    
    if  rsi_ma120['MA'].iloc[-1] < 60:
        comparison = (rsi['RSI'].tail(20) >  rsi_ma120['MA'].tail(20)).all()
        if comparison.all():
            return True
    
    return False

def chart_filter_volume_uptrend(code):
    data = get_stock_data(code, 200)
    if data.empty:
        return False
    
    volume_count = data[['Volume']].notnull().all(axis=1).sum()
    if volume_count < 100:
        return False
    
    direction = pd.Series(0, index=data.index)
    direction[data['Close'] > data['Close'].shift()] = 1
    direction[data['Close'] < data['Close'].shift()] = -1
    
    # Calculate the OBV values
    obv_values = direction * data['Volume']
    obv = obv_values.cumsum()

    ma5 = obv.rolling(window=5).mean()
    ma10 = obv.rolling(window=10).mean()
    ma20 = obv.rolling(window=20).mean()

    if  ma5.iloc[-1] > ma10.iloc[-1] :
        if ma10.iloc[-1] > ma20.iloc[-1]:
            return True
    
    return False
    
def chart_filter_low_price(code='021240'):
    data = get_stock_data(code, 90)
    if data.empty:
        return False
    
    r1,r2 = get_low_price(df=data, n=5)

    if (r1 < 20) and data['Close'].iloc[-1] >= r2 :
        return True
    
    else:
        return False


def get_code_name(name):
    with open('stock_code.json') as file:
        codes = json.load(file)
    res = [v for k, v in codes.items() if k == name]
    if len(res) >0:
        return res[0]
    else:
        return ''

def get_stock_data_time(code, startTime, endTime):
    try:
        df = fdr.DataReader(code, startTime, endTime)
        time.sleep(DELAY_SHORT)
        return df
    except:
        return pd.DataFrame()

def get_df(name, startTime=None, endTime=None):
    if endTime == None:
        now = datetime.datetime.now()
        endTime = now.strftime('%Y-%m-%d')
    
    if startTime == None:
        now = datetime.datetime.now()
        before = now - datetime.timedelta(days=365)
        startTime = before.strftime('%Y-%m-%d')

    if name.isnumeric():
        code = name
    else:
        code = get_code_name(name)

    pattern = r'^[A-Z]{1,5}$'
    if code != '':
        return get_stock_data_time(code, startTime=startTime, endTime=endTime)

    elif re.match(pattern, name):
        return get_stock_data_time(name, startTime=startTime, endTime=endTime)

    else:
        return {}


def reduce_data(df):
    try:
        # Create a new DataFrame with a fixed price range

        # df['Close'] = df['Close'].astype(int)
        df['Amount'] = df['Volume'] * df['Close']
        df['PercentOfAmount'] = df['Amount'] / df['Amount'].sum() * 100
        df = df.sort_values('Close')

        max = df['Close'].max() # (df['Close'].max() // 100) * 100 # df['Close'].max()
        min = df['Close'].min() # (df['Close'].min() // 100) * 100 # df['Close'].min()
        # diff = (max - min) / (n)
        diff = round(df['Close'].mean() * 0.02)
        price_range = pd.interval_range(start=min-diff, end=max, freq=diff)
        df2 = pd.DataFrame({
            'PriceRange': pd.cut(df['Close'], price_range),
            'Volume' : df['Volume'],
            'PercentOfAmount': df['PercentOfAmount']
        })
        
        midpoints = pd.Series(price_range.mid, index=price_range)
        df2['Close'] = df2['PriceRange'].apply(lambda x: midpoints[x.right]).astype(float)
        df3 = df2.groupby('Close').sum(numeric_only=True).reset_index()
        
        dict_data = df3.set_index('Close')['PercentOfAmount'].to_dict()
        avg_value = (sum(dict_data.values()) / len(dict_data))*1.5
        dict_data = {round(k):round(v,2) for k,v in dict_data.items() if v > avg_value}
        price_lines = dict(sorted(dict_data.items(), key=lambda item: item[1], reverse=True))
        
        return price_lines
    
    except (Exception, RuntimeWarning):
        exc_type, exc_value, exc_traceback = sys.exc_info()
        print(f"An error occurred on line {exc_traceback.tb_lineno}: {exc_type} - {exc_value}")
        traceback.print_tb(exc_traceback)
        return {}

def trendline(name, df):
    try:
        macd = MACD(df=df, n_fast=5, n_slow=20, n_signal=12, column='Volume')
        top_20 = macd.nlargest(int(len(df)/20), 'MACD')
        top_20['Ratio'] = top_20['MACD'] / top_20['Signal']
        top_20_top = top_20.nlargest(10, 'Ratio')
        
        tmp_min = df['Close'].mean()
        tmp_date = None
        len_after_min = 0
        min_idx = df.index[0]
        
        for i, row in top_20_top.iterrows():
            if tmp_min > df[i:]['Close'].min():
                tmp_min = df[i:]['Close'].min()
                min_idx = df.index[df['Close'] == df[i:]['Close'].min()][0]

        df = get_df(name, startTime=min_idx.strftime('%Y-%m-%d'))
        
        df['Number'] = np.arange(len(df))+1
        df_high = df
        df_low = df
        slope_tmp = df['Close'].iloc[-1] / 50
        # higher points are returned
        while len(df_high) > 20:
            slope, intercept, r_value, p_value, std_err = linregress(x=df_high['Number'], y=df_high['High'])
            df_high = df_high.loc[df_high['High'] > slope * df_high['Number'] + intercept]
            
        # lower points are returned
        while len(df_low) > 20:
            slope, intercept, r_value, p_value, std_err = linregress(x=df_low['Number'], y=df_low['Low'])
            df_low = df_low.loc[df_low['Low'] < slope * df_low['Number'] + intercept]

        slope_up, intercept_up, r_value, p_value, std_err = linregress(x=df_high['Number'], y=df_high['Close'])
        if abs(slope_up) < slope_tmp:
            df['Uptrend'] = round(slope_up * df['Number'] + intercept_up)
    
        slope_down, intercept_down, r_value, p_value, std_err = linregress(x=df_low['Number'], y=df_low['Close'])
        if abs(slope_down) < slope_tmp:
            df['Downtrend'] = round(slope_down * df['Number'] + intercept_down)

        # print(slope_up, slope_down)

        # Calculate the difference between the means of the two groups
        if 'Uptrend' in df and 'Downtrend' not in df :
            df['diff'] = df['Uptrend'] - df['Close']
            mean_diff = df['diff'].max()
            df['Downtrend'] = df['Uptrend'] - mean_diff
        
        if 'Downtrend' in df and 'Uptrend' not in df :
            df['diff'] = df['Close'] - df['Downtrend']
            mean_diff = df['diff'].max()
            df['Uptrend'] = df['Downtrend'] + mean_diff
        
        if 'Downtrend' in df and 'Uptrend' in df :
            df['Midtrend'] = (df['Uptrend'] + df['Downtrend']) / 2
        
        if 'Downtrend' not in df and 'Downtrend' not in df :
            return {}
        
        return df
    except (Exception, RuntimeWarning):
        exc_type, exc_value, exc_traceback = sys.exc_info()
        print(f"An error occurred on line {exc_traceback.tb_lineno}: {exc_type} - {exc_value}")
        traceback.print_tb(exc_traceback)
        return {}
   
def two_diff(p1, p2):
    return round(100*(p2-p1)/p1, 2)

def set_dict_price(dict, price, value):
    if price in dict:
        dict[price] += value
    else:
        dict[price] = value
        
    return dict
        
def get_annual_profit(df, res):
    try:
        
        sum = 0
        for i in res:
            sum += res[i]
        
        avg = (sum / len(res))*1.2

        price = df['Close'].iloc[-1]
        upper_price = round(df['Uptrend'].iloc[-1], 2)
        lower_price = round(df['Downtrend'].iloc[-1], 2)
        mid_price = round(df['Midtrend'].iloc[-1], 2)

        res = set_dict_price(res, upper_price, avg)
        res = set_dict_price(res, mid_price, avg)
        res = set_dict_price(res, lower_price, avg)

        매수가격 = 0
        매도가격 = 0
        손절가격 = 0
        down_p = 0
        up_p = 0
        sorted_dict = dict(sorted(res.items(), key=lambda x: abs(x[0] - df['Close'].iloc[-1])))

        if two_diff(lower_price, upper_price) < 10:
            avg = avg*1.5
            매도가격 = price * 1.1

        for i in sorted_dict:
            if i < price and down_p > avg and 손절가격 == 0:
                손절가격 = i
                
            if i < price and down_p < avg:
                down_p += sorted_dict[i]
                매수가격 = i
                
            elif i > price*1.04 and up_p < avg:
                up_p += sorted_dict[i]
                매도가격 = i
        
        if 매수가격 == 0:
            if abs(two_diff(price, next(iter(sorted_dict)))) < 2:
                매수가격 = next(iter(sorted_dict))
                
        if 매도가격 == 0:
            매도가격 = list(sorted_dict.keys())[-1]
        
        if 매수가격 == 0 or 매도가격 == 0:
            return (False, 0, 0)

        # 손해 = two_diff(매수가격, 매수가격*0.95)
        if 손절가격 == 0:
            손절가격 = 매수가격*0.98
            
        손해 = two_diff(매수가격, 손절가격)
        이익 = two_diff(매수가격, 매도가격)
        손익차 = round(이익+손해, 2)

        if len(df['Midtrend']) > 1 and price != 0:
            if (df['Midtrend'].iloc[-1] - df['Midtrend'].iloc[-2]) != 0:
                k = 365 / (이익 / (100*(df['Midtrend'].iloc[-1] - df['Midtrend'].iloc[-2]) / price))
            else:
                k = 365 / (이익 / (100*(df['Downtrend'].iloc[-1] - df['Downtrend'].iloc[-2]) / price))
        else:
            k = 365 / (이익 / (100*(df['Downtrend'].iloc[-1] - df['Downtrend'].iloc[-2]) / price))
        
        연환산수익률 = round(k*손익차, 2)
        매수가격차이 = two_diff(price, 매수가격)
        msg = '매수:{}({}%), 매도:{}, 손익차:{}%, 연수익률:{}%'.format(매수가격, 매수가격차이, 매도가격, 손익차, 연환산수익률)
        res_data = {}
        res_data['매수가격'] = 매수가격
        res_data['매도가격'] = 매도가격
        res_data['손익차'] = 손익차
        res_data['연환산수익률'] = 연환산수익률
        res_data['매수가격차이'] = 매수가격차이
        res_data['손절가격'] = 손절가격

        if price > upper_price or 매도가격 > upper_price*1.5:
            return (False, 0, 0)
        
        return (True, 연환산수익률, res_data)
        
    except (Exception, RuntimeWarning):
        exc_type, exc_value, exc_traceback = sys.exc_info()
        print(f"An error occurred on line {exc_traceback.tb_lineno}: {exc_type} - {exc_value}")
        traceback.print_tb(exc_traceback)
        return (False, 0, 0)

def multi_annual(name):    
    df = get_df(name)
    res = reduce_data(df)
    if len(res) == 0:
        return False

    df = trendline(name, df)
    if len(df) < 5:
        return False
 
    result = get_annual_profit(df, res)
    
    if result[0]:
        return True
    
    return False

def single_annual(name):    
    df = get_df(name)
    res = reduce_data(df)
    if len(res) == 0:
        return [False]

    df = trendline(name, df)
    if len(df) < 5:
        return [False]
 
    result = get_annual_profit(df, res)
    
    show_chart(name, df, res)
    if result[0]:
        return [True , result[2]]
    
    return [False]

def show_chart(name, data, dict_values):
    plt.rc('font', family='Malgun Gothic')

    # Create a Matplotlib figure and axis object
    fig, ax = plt.subplots()
    
    # Plot the candlestick chart
    # ax.plot(data.index, data['Open'], color='green', label='Open')
    ax.plot(data.index, data['Close'], color='red', label='Close')
    # ax.vlines(data.index, ymin=data['Low'], ymax=data['High'], color='black', label='High-Low')

    # iterate over the dictionary and plot horizontal lines with color intensity proportional to the value
    for price, value in dict_values.items():

        color = mcolors.Normalize(vmin=2, vmax=max(dict_values.values()))(value)
        ax.axhline(y=price, color=plt.cm.Blues(color), label=price)

    ax2 = ax.twiny() # ax2 and ax1 will have common y axis and different x axis, twiny
    if 'Uptrend' in data:
        ax2.plot(data.Number, data.Uptrend, label="upper", color='Blue')
    if 'Downtrend' in data:
        ax2.plot(data.Number, data.Downtrend, label="lower", color='Blue')
    if 'Midtrend' in data:
        ax2.plot(data.Number, data.Midtrend, label="mid", color='Green')
    
    # Add a legend and labels to the charts
    ax.set_xlabel('Date')
    ax.set_ylabel('Price')
    ax.set_title(name)

    # Show the chart
    plt.show()

def 종목찾기(ticker):

    금융주 = ['024110', '105560', '055550', '086790', '377300',
           '000810', '016360', '032830', '006800', '005940', 
           '005830', '039490', '008560', '041190', '316140', '029780', 
           '001450', '088350', '071050', '082640', '138040', '138930',
           '323410', '003540', '003690', '078020', '000370', '030610', 
           '003530', '139130', '175330', '000400', '123890', '010050', 
           '034830', '023590', '027360', '001510', '032190', '038540']
    
    conds = {'매출액': [0, 0.05], 'BPS': [0, 0.03],  # 성장성
             'ROE': [5, -1], '영업이익률': [5, -1], '영업이익': [20, -1], # 수익성
            #  'PBR': [3.0, 0], 'PER':[20.0, 0], 
             '부채비율':[180, 0],
             '발행주식수' : [10, 0],
             } # 안정성
    
    if ticker in 금융주:
        conds['부채비율'] = [2000, 0] 
    
    if not 재무재표검사(ticker, conds):
        return
    
    # if not 경쟁사비교(ticker, rank=2.9):
    #     return
    
    negative = ['급감', '침체', '악화', '부진', '축소', '적자전환', '실적 감소', '수익성 악화', '이익 감소']
    if not 정보검사(ticker, negative):
        return

    if not 차트검사(ticker):
        return
    
    return ticker

def multiProcess():
    now = datetime.datetime.now()
    now_date = now.strftime('%Y%m%d')

    # 최신 영업일 찾기
    tickers = []
    for i in range(10):
        try:
            d = (now - datetime.timedelta(days=i)).strftime('%Y%m%d')
            kospi_list = stock.get_market_ticker_list(d, market='KOSPI')
            if len(kospi_list) > 0:
                kosdaq_list = stock.get_market_ticker_list(d, market='KOSDAQ')
                tickers = kospi_list + kosdaq_list
                break
        except:
            continue
    
    if not tickers:
        try:
            # FDR fallback
            df_kospi = fdr.StockListing('KOSPI')
            df_kosdaq = fdr.StockListing('KOSDAQ')
            tickers = df_kospi['Code'].tolist() + df_kosdaq['Code'].tolist()
        except:
            pass

    if not tickers:
        try:
            # DB fallback
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tickers = [row[0] for row in cur.fetchall() if row[0].isdigit() and len(row[0]) == 6]
            conn.close()
        except:
            pass

    if not tickers:
        print("종목 리스트를 가져오는 데 실패했습니다.")
        return

    result_list = []
    pool = Pool(multiprocessing.cpu_count())
    try:
        for result in tqdm.tqdm(pool.imap_unordered(종목찾기, tickers), total=len(tickers)):
            if result != None:
                result_list.append(result)
    finally:
        pool.close()
        pool.join()

    save_list(result_list)

def get_stock_headline(code="005930"):
    url = 'http://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A'+code+'&cID=&MenuYn=Y&ReportGB=&NewMenuID=101&stkGb=701'

    response = requests.get(url)
    html = response.text
    soup = bs(html, 'html.parser')
    tag = soup.select_one('#bizSummaryHeader')
    if tag:
        return tag.get_text(strip=True).replace('\xa0', ' ')
    return ""


if __name__ == '__main__':
    # multiProcess()
    ticker = '두산에너빌리티'
    r1 = single_annual(ticker)
    if r1[0]:
        print(ticker, r1[1])
    
    # condition = '발행주식수'
    # print(get_finance_info(code='055550', condition=condition))
    