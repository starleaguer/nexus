#!/usr/bin/env python
# -*- coding: utf-8 -*-


from multiprocessing import Pool, Process, Manager
from urllib.request import urlopen, Request
from bs4 import BeautifulSoup as bs
# from pykrx import stock  # Unstable, removed as per user request
from pystocklib.common import *

import requests
import sqlite3
import FinanceDataReader as fdr
import csv
import datetime
import pandas as pd
import tqdm
import multiprocessing
import os
import json
import gspread
import re


DICT_DATA = "./stock_data/"

# csv 파일을 만들기 위한 함수
def csv_writer():
    # 현재 시간
    now = datetime.datetime.now()
    with open('csv_writer_test_{}{}_{};{}.csv'.format(now.strftime('%m'),now.strftime('%d'), now.strftime('%H'),
                                                         now.strftime('%M')),mode='w', newline='') as res_file:
        csv_w = csv.writer(res_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)

        flag = False
        json_file_list = get_file_list()

        for i in json_file_list:
            with open(i) as f:
                json_object = json.load(f)
                json_object['code'] = '#' + json_object['code']
                if flag is False:
                    csv_w.writerow(json_object.keys())
                csv_w.writerow(json_object.values())

            flag = True


def get_file_list():
    path = DICT_DATA
    file_list = os.listdir(path)
    file_list_stock = ["{}{}".format(DICT_DATA, file) for file in file_list if file.endswith(".json")]
    return file_list_stock


def avg_list(value_list):
    if len(value_list) == 0:
        return 0
    if type(value_list[0]) is str:
        tmp_list = []
        for i in value_list:
            if i != "":
                tmp_list.append(float(i.replace(",", "")))
        value_list = tmp_list

    return round(sum(value_list)/len(value_list), 2)


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


#EPS, BPS
def bps_future(ticker):
    timestamp = str(round(datetime.datetime.now().timestamp()*1000))
    url = 'http://comp.fnguide.com/SVO2/json/chart/05/chart_A' + ticker +'_D.json?_=' + timestamp
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        html_text = urlopen(req).read()
        data = json.loads(html_text.decode('utf-8-sig'))
        bps_list = []
        for i in data['01_Y']:
            if i['VAL2'] != '-':
                bps_list.append(float(i['VAL2'].replace(",", "")))

        bps = float(data['01_Q'][3]['VAL2'].replace(",", ""))
        res = bps * (1+sungjang(bps_list))

        return res

    except Exception as e:
        # print(f"Error in bps_future for {ticker}: {e}")
        return 0


#기업가치 적정주가 PBR*BPS
def future_price(ticker):
    timestamp = str(round(datetime.datetime.now().timestamp()*1000))
    url = 'http://comp.fnguide.com/SVO2/json/chart/01_06/chart_A' + ticker +'_D.json?_=' + timestamp
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        html_text = urlopen(req).read()
        data = json.loads(html_text.decode('utf-8-sig'))
        pbr_list = []
        pbr_n = float(data['CHART_B'][1]['NAME'].replace("X", ""))
        for i in data['CHART']:
            if i['PRICE'] != '-' and i['B1'] != '':
                pbr_list.append(float(i['PRICE'])/(float(i['B1'])/pbr_n))

        res = 0
        if len(pbr_list) > 0:
            pbr_avg = sum(pbr_list)/len(pbr_list)
            bps_f = bps_future(ticker)
            res = bps_f * pbr_avg

        return {"미래가격": round(res)}

    except Exception as e:
        # print(f"Error in future_price for {ticker}: {e}")
        return {"미래가격": 1}


def data_config(data):

    res = {}
    for i in data:
        if type(data[i]) == list:
            if i == "발행주식수":
                res[i] = data[i][2]
            else:
                res[i] = data[i][2]
                res[i + "_A성장률"] = sungjang(data[i][0:3])
                res[i + "_Q성장률"] = sungjang(data[i][4:7])
        else:
            res[i] = data[i]

    return res


def data_config_y(data):

    res = {}
    for i in data:
        if type(data[i]) == list:
            if i == "발행주식수":
                res[i] = data[i][4]
            else:
                res[i] = data[i][4]
                res[i + "_A성장률"] = sungjang(data[i][0:5])
        else:
            res[i] = data[i]

    return res


def price_mkt(ticker):
    timestamp = str(round(datetime.datetime.now().timestamp()*1000))
    url = 'http://comp.fnguide.com/SVO2/json/chart/01_01/chart_a' + ticker +'_3m.json?_=' + timestamp
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    res = {"시가총액": -1, "가격": -1}
    try:
        html_text = urlopen(req).read()
        data = json.loads(html_text.decode('utf-8-sig'))

        price = float(data['CHART'][-1]['J_PRC'].replace(",",""))
        res = {"시가총액": float(data['CHART'][-1]['MKT_CAP'].replace(",","")), "가격": price}
    except Exception as e:
        # print(f"Error in price_mkt for {ticker}: {e}")
        return {"시가총액": -1, "가격": -1}

    return res


def snapshot_3y(ticker):
    url = 'http://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A'+ ticker +'&cID=&MenuYn=Y&ReportGB=&NewMenuID=101&stkGb=701'

    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    html_text = urlopen(req).read()

    soup = bs(html_text, 'lxml')
    d = soup.find_all(id='highlight_D_Y')

    res = {"이자수익": 0, "매출액": 0, "영업이익": 0, "지배주주순이익": 0, "당기순이익": 0, "자산총계": 0, "부채총계": 0, "자본총계": 0, "자본금": 0, "부채비율": 0
           , "영업이익률": 0, "지배주주순이익률": 0, "ROA": 0, "ROE": 0, "EPS": 0, "BPS": 0, "DPS": 0, "PER": 0, "PBR": 0}
    for i in res:
        res_list = []
        if len(d) > 0:
            c = d[0].find_all_next(text=i)
            if len(c) > 0:
                data = c[0].find_all_next(class_="r", limit=8)
                for v in data:
                    if v.get_text(strip=True) != '':
                        res_list.append(float(v.get_text(strip=True).replace(",","").replace("N/A", "-1").replace("완전잠식","-1").replace("(IFRS)","")))
                    else:
                        res_list.append(-1)

                res[i] = res_list

    d = soup.find_all(id='corp_group2')
    corp = {"12M PER": 1,  "배당수익률": 1}
    for i in corp:
        if len(d) > 0:
            c = d[0].find_all_next(text=i)
            res[i] = float(c[corp[i]].find_next('dd').get_text().replace("%","").replace("-","-1").replace(",",""))

    return data_config_y(res)


def snapshot(ticker):
    url = 'http://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A'+ ticker +'&cID=&MenuYn=Y&ReportGB=&NewMenuID=101&stkGb=701'

    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    html_text = urlopen(req).read()

    row = ["이자수익", "매출액", "영업이익", "지배주주순이익", "당기순이익", "자산총계", "부채총계", "자본총계", "자본금", "부채비율"
           , "유보율", "영업이익률", "지배주주순이익률", "ROA", "ROE", "EPS", "BPS", "DPS", "PER", "PBR", "발행주식수", "배당수익률"]

    soup = bs(html_text, 'lxml')
    d = soup.find_all(id='highlight_D_A')

    res = {"이자수익": 0, "매출액": 0, "영업이익": 0, "지배주주순이익": 0, "당기순이익": 0, "자산총계": 0, "부채총계": 0, "자본총계": 0, "자본금": 0, "부채비율": 0
           , "유보율": 0, "영업이익률": 0, "지배주주순이익률": 0, "ROA": 0, "ROE": 0, "EPS": 0, "BPS": 0, "DPS": 0, "PER": 0, "PBR": 0, "발행주식수": 0, "배당수익률": 0,
           "N_PER": 0, "N_12M PER": 0, "N_PBR": 0, "N_배당수익률": 0}
    for i in row:
        res_list = []
        if len(d) > 0:
            c = d[0].find_all_next(text=i)
            if len(c) > 0:
                data = c[0].find_all_next(class_="r", limit=8)
                for v in data:
                    if v.get_text(strip=True) != '':
                        res_list.append(float(v.get_text(strip=True).replace(",","").replace("N/A", "-1").replace("완전잠식","-1").replace("(IFRS)","")))
                    else:
                        res_list.append(-1)

                res[i] = res_list

    d = soup.find_all(id='corp_group2')
    corp = {"PER": 0, "12M PER": 1, "PBR": 0, "배당수익률": 1}
    for i in corp:
        if len(d) > 0:
            c = d[0].find_all_next(text=i)
            res['N_'+i] = float(c[corp[i]].find_next('dd').get_text().replace("%","").replace("-","-1").replace(",",""))

    return data_config(res)

# 투자지표
def tooja(ticker):
    timestamp = str(round(datetime.datetime.now().timestamp()*1000))
    url = 'http://comp.fnguide.com/SVO2/json/chart/05_05/A' + ticker +'.json?_=' + timestamp
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        html_text = urlopen(req).read()
        data = json.loads(html_text.decode('utf-8-sig'))

        res = {"베타": data['CHART_D'][0]['VAL1'], "배당성":data['CHART_D'][1]['VAL1'], "수익건전성":data['CHART_D'][2]['VAL1'],
                    "성장성":data['CHART_D'][3]['VAL1'], "기업투자":data['CHART_D'][4]['VAL1'], "거시경제":data['CHART_D'][5]['VAL1'], "모멘텀":data['CHART_D'][6]['VAL1'],
                    "단기리턴":data['CHART_D'][7]['VAL1'], "기업규모":data['CHART_D'][8]['VAL1'], "거래도":data['CHART_D'][9]['VAL1'], "밸류":data['CHART_D'][10]['VAL1'],
                    "변동성":data['CHART_D'][11]['VAL1']}
    except Exception as e:
        res = {"베타": 0, "배당성": 0, "수익건전성": 0,
                    "성장성":0, "기업투자": 0, "거시경제": 0, "모멘텀": 0,
                    "단기리턴": 0, "기업규모": 0, "거래도": 0, "밸류": 0,
                    "변동성": 0}
        return res

    return res


def get_stock_list():
    tickers = []
    
    # 1순위: FinanceDataReader
    try:
        df_kospi = fdr.StockListing('KOSPI')
        df_kosdaq = fdr.StockListing('KOSDAQ')
        tickers = df_kospi['Code'].tolist() + df_kosdaq['Code'].tolist()
    except Exception as e:
        # print(f"fdr failure: {e}")
        pass

    # 2순위: stock_code.json
    if not tickers:
        try:
            if os.path.exists('stock_code.json'):
                with open('stock_code.json', 'r', encoding='utf-8') as f:
                    codes = json.load(f)
                    tickers = list(codes.values())
        except:
            pass

    # 3순위: 로컬 DB
    if not tickers:
        try:
            if os.path.exists('korea_stock.db'):
                conn = sqlite3.connect('korea_stock.db', timeout=30)
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tickers = [row[0] for row in cur.fetchall() if row[0].isnumeric()]
                conn.close()
        except:
            pass

    return tickers


def multiProcess():
    tickers = get_stock_list()
    if not tickers:
        print("종목 리스트를 가져오지 못했습니다.")
        return

    pool = Pool(multiprocessing.cpu_count())
    try:
        for _ in tqdm.tqdm(pool.imap_unordered(saveStockJsonfile, tickers), total=len(tickers)):
            pass
    finally:
        pool.close()
        pool.join()


def saveStockJsonfile(t):
    # print("PID : " + str(os.getpid()) + t)
    res = {}
    name = ""
    # stock_code.json에서 종목명 찾기
    try:
        if os.path.exists('stock_code.json'):
            with open('stock_code.json', 'r', encoding='utf-8') as f:
                codes = json.load(f)
                # 역방향 매핑 찾기
                for k, v in codes.items():
                    if v == t:
                        name = k
                        break
    except:
        pass
    
    res['종목명'] = name if name else t
    res['code'] = str(t)
    res.update(price_mkt(t))
    res.update(tooja(t))
    res.update(snapshot(t))
    res.update(vpTest(t, 90))
    res.update(vpTest(t, 180))
    res.update(vpTest(t, 365))

    directory = DICT_DATA
    if not os.path.exists(directory):
        os.makedirs(directory)

    with open(directory+t+".json", "w") as f:
        json.dump(res, f, indent=4)


def make_excel():
    _gc = gspread.service_account(filename="./google.json")
    sheet_name = "naver_" + datetime.datetime.now().strftime("%Y%m%d")
    print(sheet_name)
    sh = _gc.create(sheet_name)
    sh.share('dudjun87@gmail.com', perm_type='user', role='writer')
    print(sh)


# list_of_lists = worksheet.get_all_values()
# list_of_dicts = worksheet.get_all_records()

# amount_re = re.compile(r'(Big|Enormous) dough')
# cell = worksheet.find(amount_re)

# worksheet.row_count

# 특정 범위의 값을 가져오기
# cell_list = worksheet.range('A1:C7')
def read():
    gc = gspread.service_account(filename="./google.json")
    sh = gc.open("asset").worksheet("test")
    print(sh.get('A1'))

    # for cell in sh.findall('hello'):
    #     print(cell.value, cell.row, cell.col)
    # cell_list = sh.range('A1:C7')
    # val = worksheet.acell('B1').value
    # val = worksheet.cell(1, 2).value

    # sh.update_acell('A2', "python")
    sh.update_cell(1, 2, "aa")
    # sh.update_cells(cell_list)


def gspreadWrite():
    gc = gspread.service_account(filename="./google.json")
    sh = gc.open("asset").worksheet("test")

    flag = False
    json_file_list = get_file_list()

    row = 1

    index_list = ['종목명', '시가총액', '가격', '배당성', '수익건전성' ,'성장성', '기업투자', 'ROE', 'EPS', 'PER', 'PBR']
    indx_end = chr(ord('A') + len(index_list))

    for i in json_file_list:
        with open(i) as f:
            json_object = json.load(f)
            json_object['code'] = '#' + json_object['code']
            if int(json_object['시가총액']) < 0:
                continue

            row += 1

            if flag is False:
                _range = "{}{}:{}{}".format('A', '1', indx_end, '1')
                cell_list = sh.range(_range)

                for i, val in enumerate(index_list):
                    cell_list[i].value = val
                sh.update_cells(cell_list)

            _range = "{}{}:{}{}".format('A', str(row), indx_end, str(row))
            cell_list = sh.range(_range)

            for i, val in enumerate(index_list):
                if json_object[val] is not None:
                    cell_list[i].value = json_object[val]
            sh.update_cells(cell_list)

        flag = True


def vpTest(st, day):
    now = datetime.datetime.now()
    before = now - datetime.timedelta(days=day)
    df = fdr.DataReader(st, before.strftime('%Y%m%d'), now.strftime('%Y%m%d'))

    price_stack = {}
    sum_volum = 0
    for idx, row in df.iterrows():
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
            return {str(day)+'vp': -1}
            
        for key, val in price_stack.items():
            price_stack[key] = round(val*100/sum_volum,2)
        
        sorted_data = sorted(price_stack.items(), key=lambda x: x[0], reverse=True)
        # print(sorted_data)

        res = 0
    
        for i in sorted_data:
            p = int(i[0])*r
            if now >= p:
                res += i[1]
        return {str(day)+'vp': round(res)}
    
    except:
        return {str(day)+'vp': -1}


def vpPbrTest(st,day):
    # pykrx 의존성이 강해 현재 비활성화
    return {str(day)+'vpbr':-1, 'dif': -1}


def q_db(q):
    # 데이터베이스 연결
    conn = sqlite3.connect('korea_stock.db')
    cur = conn.cursor()

    # 데이터 불러오기
    cur.execute(q)
    rows = cur.fetchall()

    # 데이터 출력
    for row in rows:
        print(row)

    # 연결 종료
    conn.close()
    
    
def save_year_data(code="005930"):
    try:
        # 데이터를 가져올 URL
        url = 'http://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A'+ code +'&cID=&MenuYn=Y&ReportGB=&NewMenuID=101&stkGb=701'

        # requests 라이브러리를 사용하여 HTML 코드를 가져옴
        response = requests.get(url)

        # BeautifulSoup 라이브러리를 사용하여 HTML 코드에서 원하는 데이터를 추출
        soup = bs(response.content, 'html.parser')
        table = soup.select_one('#highlight_D_Y > table')
        rows = table.select('tr')
        years = rows[1].select('th')

        data = {}
        result = {}
        
        year_keys = []
        for y in years:
            name = y.text.strip()
            match = re.search(r'\d{4}', name)
            if match:
                year_key = match.group()
                if "(E)" in name:
                    year_key += "(E)"
            else:
                year_key = name[0:4]
            year_keys.append(year_key)
            result[year_key] = {}
            
        for row in rows[2:]:
            name = row.select('th')[0].text.strip()
            pattern = r'^[^(|\s]+'
            match = re.search(pattern, name)
            if match:
                name = match.group()
                
            data[name] = [td.text.strip() for td in row.select('td')]

        for i in range(min(len(year_keys), len(list(data.values())[0]) if data else 0)):
            key = year_keys[i]
            for d in data:
                if i < len(data[d]):
                    result[key].update({d : data[d][i]})
        
        conn = sqlite3.connect('korea_stock.db', timeout=30)
        cursor = conn.cursor()

        # 테이블 생성
        q = '''CREATE TABLE IF NOT EXISTS "%s" (year TEXT, name TEXT, value TEXT)''' % code
        cursor.execute(q)
        
        for year in result:
            for name in result[year]:
                value = result[year][name]
                cursor.execute('''INSERT INTO "%s" VALUES (?, ?, ?)''' % code, (year, name, value))
        # BeautifulSoup 라이브러리를 사용하여 HTML 코드에서 원하는 데이터를 추출
        soup = bs(response.content, 'html.parser')
        table = soup.select_one('#highlight_D_Q > table')
        rows = table.select('tr')
        qters = rows[1].select('th')
        
        data = {}
        result = {}
        
        qter_keys = []
        for q in qters[:8]: # 늘어날 수 있는 분기 대응
            name = q.text.strip()
            match = re.search(r'\d{4}/\d{2}', name)
            if match:
                q_key = match.group()
                if "(E)" in name:
                    q_key += "(E)"
            else:
                q_key = name[0:7]
            qter_keys.append(q_key)
            result[q_key] = {}

        for row in rows[2:]:
            name = row.select('th')[0].text.strip()
            pattern = r'^[^(|\s]+'
            match = re.search(pattern, name)
            if match:
                name = match.group()
                
            data[name] =  [td.text.strip() for td in row.select('td')]

        for i in range(min(len(qter_keys), len(list(data.values())[0]) if data else 0)):
            key = qter_keys[i]
            for d in data:
                if i < len(data[d]):
                    result[key].update({d : data[d][i]})        
        
        for qter in result:
            for name in result[qter]:
                value = result[qter][name]
                cursor.execute('''INSERT INTO "%s" VALUES (?, ?, ?)''' % code, (qter, name, value))

        conn.commit()
        conn.close()

    except:
        print('error')
        pass


def save_tooja_data(code="005930"):
    try:
        tooja_res = tooja(code)
        conn = sqlite3.connect('korea_stock.db', timeout=30)

        # 데이터베이스 커서 생성
        cursor = conn.cursor()

        # 테이블 생성
        q = '''CREATE TABLE IF NOT EXISTS "%s" (year TEXT, name TEXT, value TEXT)''' % code
        cursor.execute(q)

        for name in tooja_res:
            year = datetime.datetime.now().year
            value = tooja_res[name]
            cursor.execute('''INSERT INTO "%s" VALUES (?, ?, ?)''' % code, (year, name, value))
        conn.commit()
        conn.close()
    except:
        print('error')
        pass


import sqlite3

def delete_duplicate_data(table_name, unique_column):
    # Connect to the SQLite database
    
    conn = sqlite3.connect('korea_stock.db')
    cursor = conn.cursor()

    # Identify duplicate rows based on the unique column
    cursor.execute(f"""
        SELECT {unique_column}, COUNT(*)
        FROM "{table_name}"
        GROUP BY {unique_column}
        HAVING COUNT(*) > 1
    """)

    # Fetch all duplicate rows
    duplicate_rows = cursor.fetchall()

    # Iterate through each duplicate row
    for row in duplicate_rows:
        unique_value = row[0]

        # Keep the row with the lowest primary key or rowid
        cursor.execute(f"""
            DELETE FROM "{table_name}"
            WHERE rowid NOT IN (
                SELECT MIN(rowid)
                FROM "{table_name}"
                WHERE {unique_column} = ?
            )
        """, (unique_value,))

    # Commit changes and close connection
    conn.commit()
    conn.close()


def get_code_name(name_or_code):
    try:
        with open('stock_code.json', 'r', encoding='utf-8') as file:
            codes = json.load(file)
        if name_or_code in codes:
            return codes[name_or_code]
        # 이미 코드인 경우 그대로 반환
        return name_or_code
    except:
        return name_or_code


if __name__ == "__main__":

    # 예: code = '005930' 또는 code = '삼성전자'
    code = '삼성전자'

    if not code.isnumeric():
        code = get_code_name(code)

    # save_year_data(code)
    # save_tooja_data(code)
    q_db('''SELECT * FROM "%s" ''' % (code))
    
    # cnt = 0
    # tickers = get_stock_list()
    # for t in tickers:
    #     cnt += 1
    #     print(cnt)
    #     save_year_data(t)
    #     save_tooja_data(t)

    # multiProcess()
    
