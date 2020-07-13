import threading
import time
from collections import deque
import pandas as pd
import argparse
import datetime
import pickle
import websockets
import asyncio
import requests
import numpy as np
import json

global predict
# spy model
infile = open('sequential-model.sav', 'rb')
classifier = pickle.load(infile)
infile.close()

global last_price_short
global last_price_long
global thirty_mins
global lot
global data_cleaned
global state
global id_order
state = 'to_order'
global quantity_of_stock
global stop
stop = False
global predict_proba
global bet_size
global end_timer
global bail
bail = False
global short
global long
global session_id
global dynamic_stop
global realtime_last_price_long
global realtime_last_price_short
global realtime_ask_long
global realtime_ask_short
global realtime_bid_long
global realtime_bid_short
global secure_profit
global fulfilled
global secure_quantity
global trail_stop
global start_trail
global reference_price
global cool_start
global last_predicts
global target
global band_stop
last_predicts = deque(maxlen=5)
start_trail = False
trail_stop = False
secure_quantity = 0
fulfilled = False
secure_profit = False
short = 'SPXU'
long = 'SPXL'


def stream_id():
    sess = requests.post('https://api.tradier.com/v1/markets/events/session',
                         data={},
                         headers={'Authorization': 'Bearer #apikey',
                                  'Accept': 'application/json'}
                         )
    session_id_resp = sess.json()
    session_id = session_id_resp['stream']['sessionid']
    id = str('"' + session_id + '"')
    payload_Str = '{"symbols": ["SPXU", "SPXL"], "sessionid": ' + id + ', "linebreak": true}'
    return payload_Str


async def connect_and_consume():
    global realtime_last_price_long
    global realtime_bid_long
    global realtime_bid_short
    global realtime_ask_long
    global realtime_ask_short
    global realtime_last_price_short
    uri = "wss://ws.tradier.com/v1/markets/events"
    payload_Str = stream_id()
    async with websockets.connect(uri) as websocket:
        payload = payload_Str

        await websocket.send(payload)
        print('Stream active')
        while True:
            response = await websocket.recv()
            values = json.loads(response)
            if values['symbol'] == 'SPXL':
                if values['type'] == 'timesale':
                    realtime_last_price_long = float(values['last'])
            if values['symbol'] == 'SPXU':
                if values['type'] == 'timesale':
                    realtime_last_price_short = float(values['last'])
            if values['symbol'] == 'SPXU':
                if values['type'] == 'quote':
                    realtime_bid_short = float(values['bid'])
                    realtime_ask_short = float(values['ask'])
            if values['symbol'] == 'SPXL':
                if values['type'] == 'quote':
                    realtime_bid_long = float(values['bid'])
                    realtime_ask_long = float(values['ask'])


def stream():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
        asyncio.get_event_loop().run_until_complete(connect_and_consume())
    except:
        websockets.WebSocketException
        print('Stream failed, reconnecting.')
        stream()


def sizing():
    global predict_proba
    global bet_size
    max_value = np.max(predict_proba)
    if max_value > .8:
        bet_size = 1
    if max_value > .6:
        bet_size = 1
    if max_value > .55:
        bet_size = .85
    if max_value > .5:
        bet_size = .8
    if max_value < .5:
        bet_size = .5


def trail(cost_share, price, start):
    global start_trail
    global reference_price
    global dynamic_stop
    start_price = start
    start_trail_price = float((cost_share + start)/2)
    end_trail_price = (cost_share * 1.03)
    diff_trail = end_trail_price - start_trail_price
    if not start_trail:
        if price >= start_price:
            print('Trailing stop started.')
            start_trail = True
    if start_trail:
        if price > reference_price:
            reference_price = price
            delta = reference_price - cost_share
            trail_delta = reference_price - start_trail_price
            adaptive_add = ((trail_delta / diff_trail) * 0.4)
            dynamic_stop = float(cost_share + (delta * (.5 + adaptive_add)))
            print('Current highest price: ' + str(reference_price))
        print('Trailing stop at: ' + str(dynamic_stop))
        if price < dynamic_stop:
            return True


def trade_manage(symbol):
    global realtime_last_price_short
    global realtime_last_price_long
    global realtime_bid_long
    global realtime_bid_short
    global stop
    global quantity_of_stock
    global fulfilled
    global secure_profit
    global secure_quantity
    global trail_stop
    quantity_of_stock = float(quantity_of_stock)
    realtime_last_price_short = float(realtime_bid_short)
    realtime_last_price_long = float(realtime_bid_long)
    position_response = requests.get('https://api.tradier.com/v1/accounts/<acc number>/positions',
                                     params={},
                                     headers={'Authorization': 'Bearer #apikey',
                                              'Accept': 'application/json'}
                                     )
    positions = position_response.json()
    for data, value in positions['positions'].items():
        for x in range(len(value)):
            check_symbol = value[x]['symbol']
            if check_symbol == symbol:
                cost_basis = value[x]['cost_basis']
                cost_per_share = (cost_basis / quantity_of_stock)
                stop_loss_price = float(cost_per_share - (cost_per_share*band_stop))
                take_profit_price = float(cost_per_share + (cost_per_share*target))
                # Take Profit
                if not fulfilled:
                    if not secure_profit:
                        if check_symbol == 'SPXU':
                            print('Take profit price for SPXU: ' + str(take_profit_price) + ', Current price: ' + str(
                                realtime_last_price_short))
                            if take_profit_price < realtime_last_price_short:
                                secure_profit = True
                            else:
                                secure_profit = False
                        if check_symbol == 'SPXL':
                            print('Take profit price for SPXL: ' + str(take_profit_price) + ', Current price: ' + str(
                                realtime_last_price_long))
                            if take_profit_price < realtime_last_price_long:
                                secure_profit = True
                            else:
                                secure_profit = False
                # stop-loss and trailing stop
                if check_symbol == 'SPXU':
                    check_short = trail(cost_per_share, realtime_last_price_short, take_profit_price)
                    if check_short:
                        trail_stop = True
                    print('Stop loss price for SPXU: ' + str(stop_loss_price) + ', Current price: ' + str(
                        realtime_last_price_short))
                    if stop_loss_price > realtime_last_price_short:
                        stop = True
                    else:
                        stop = False
                if check_symbol == 'SPXL':
                    check_long = trail(cost_per_share, realtime_last_price_long, take_profit_price)
                    if check_long:
                        trail_stop = True
                    print('Stop loss price for SPXL: ' + str(stop_loss_price) + ', Current price: ' + str(
                        realtime_last_price_long))
                    if stop_loss_price > realtime_last_price_long:
                        stop = True
                    else:
                        stop = False
                else:
                    return


def gain_loss():
    now = pd.Timestamp.now(tz='America/New_York').floor(freq='D')
    one_day = pd.Timedelta('1day')
    now = (now - one_day).strftime('%Y-%m-%d')
    response = requests.get('https://api.tradier.com/v1/accounts/<acc number>/gainloss',
                            params={'sortBy': 'closeDate', 'sort': 'desc'},
                            headers={'Authorization': 'Bearer #apikey',
                                     'Accept': 'application/json'}
                            )
    json_response = response.json()
    total_gain = 0
    try:
        print("Actions done for the day. Available gain and loss:")
        for data, value in json_response['gainloss'].items():
            for x in range(len(value)):
                close_date = value[x]['close_date']
                close_date = datetime.datetime.strptime(close_date, '%Y-%m-%dT%H:%S:%M.%fZ')
                close_date = close_date.strftime('%Y-%m-%d')
                if close_date == now:
                    print('Position ' + str(x + 1) + ', ' + value[x]['symbol'])
                    print('Close Date: ' + str(close_date))
                    print('Cost: ' + str(value[x]['cost']))
                    print('Gain/Loss in percent: ' + str(value[x]['gain_loss_percent']))
                    print('Gain/Loss in absolute numbers: ' + str(value[x]['gain_loss']))
                    print('Proceeds: ' + str(value[x]['proceeds']))
                    print('     ')
                    total_gain += value[x]['gain_loss']
        print('Total gain: ' + str(total_gain))
    except:
        json.decoder.JSONDecodeError
        print('No historical positions.')


def bailout():
    global state
    global bail
    if end_timer < 180:
        if state == 'to_close_long':
            close_position_long()
        if state == 'to_close_short':
            close_position_short()
        if state == 'to_order':
           # gain_loss()
            exit('Actions done for the day.')
    if end_timer >= 180:
        bail = True
        if state == 'to_close_long':
            close_position_long()
        if state == 'to_close_short':
            close_position_short()
        if state == 'to_order':
           # gain_loss()
            exit('Actions done for the day.')


def prediction():
    global predict
    global data_cleaned
    global predict_proba
    global last_predicts
    predict_data = data_cleaned.assign(
#data needed for prediction
    )
    print('Time is ' + predict_data['time'].iloc[-1])
    predict_data = predict_data.drop(['time'], axis=1)
    predict_data = predict_data.drop(['high'], axis=1)
    predict_data = predict_data.drop(['low'], axis=1)
    predict_data = predict_data.drop(['close'], axis=1)
    predict_data = predict_data.drop(['open'], axis=1)
    predict_data = predict_data.drop(['volume'], axis=1)
    recent_to_predict = predict_data.iloc[[-1]]
    predict = classifier.predict(recent_to_predict)
    predict_proba = classifier.predict_proba(recent_to_predict)
    last_predicts.append(predict)
    print('Prediction is: ' + str(predict))
    print('Class probabilities are: ' +str(predict_proba))

def build_x_data(symbol):
    global data_cleaned
    now = pd.Timestamp.now(tz='America/New_York').floor('1min')
    prev_30_min = (now - pd.Timedelta('80min')).strftime('%Y-%m-%d %H:%M')
    tomorrow = (now + pd.Timedelta('1day')).strftime('%Y-%m-%d %H:%M')
    response = requests.get('https://api.tradier.com/v1/markets/timesales',
                            params={'symbol': symbol, 'interval': '1min', 'start': prev_30_min,
                                    'end': tomorrow, 'session_filter': 'all'},
                            headers={'Authorization': 'Bearer #apikey',
                                     'Accept': 'application/json'}
                            )
    json_call = response.json()
    try:
        for data, value in json_call['series'].items():
            df_data = pd.DataFrame({
                'time': [value[x]['time'] for x in range(len(value))],
                'close': [value[x]['close'] for x in range(len(value))],
                'open': [value[x]['open'] for x in range(len(value))],
                'volume': [value[x]['volume'] for x in range(len(value))],
                'high': [value[x]['high'] for x in range(len(value))],
                'low': [value[x]['low'] for x in range(len(value))],

            })
        data_cleaned = df_data
    except:
        build_x_data(symbol)


def boll_bands(direction):
    global data_cleaned
    global target
    global band_stop
    bbands_df = pd.DataFrame(bbands(data_cleaned.close, length=15, std=3.5))
    spy_price = float(data_cleaned['close'].iloc[-1])
    if direction == 'short':
        lower_band_val = float(bbands_df['BBL_15'].iloc[-1])
        target = float((abs(spy_price - lower_band_val) / lower_band_val)*3)
        upper_band_val = float(bbands_df['BBU_15'].iloc[-1])
        band_stop = float((abs(spy_price - upper_band_val) / upper_band_val)*2)
    if direction == 'long':
        lower_band_val = float(bbands_df['BBL_15'].iloc[-1])
        upper_band_val = float(bbands_df['BBU_15'].iloc[-1])
        target = float((abs(spy_price - upper_band_val) / upper_band_val)*3)
        band_stop = float((abs(spy_price - lower_band_val) / lower_band_val)*2)

def api_close_long(quantity):
    global id_order
    realtime_long = float(realtime_bid_long)
    realtime_long = str(realtime_long)
    long_response = requests.post('https://api.tradier.com/v1/accounts/<acc number>/orders',
                                  data={'class': 'equity', 'symbol': long, 'side': 'sell',
                                        'quantity': quantity,
                                        'type': 'limit', 'duration': 'day', 'price': realtime_long},
                                  headers={'Authorization': 'Bearer #apikey',
                                           'Accept': 'application/json'}
                                  )
    long_resp = long_response.json()
    id_order = long_resp['order']['id']
    status = long_resp['order']['status']
    if ensure_execution('close', 'long'):
        return True


def close_position_long():
    trade_manage(long)
    global thirty_mins
    global secure_profit
    global quantity_of_stock
    global bail
    global secure_quantity
    global trail_stop
    now = pd.Timestamp.now(tz='America/New_York').floor('1min')
    print("Current amount of stock is: " + str(quantity_of_stock) + " SPXL")
    print('Timer is: ' + str(thirty_mins))

    if predict == 2:
        timer()

    if now >= thirty_mins:
        if predict == 2:
            timer()
        if predict != 2:
            close = api_close_long(quantity_of_stock)
            if close:
                cooldown_now()
                transition('cooldown')
                print('Long position CLOSED due to timer')
    elif last_predicts.count(0) == 5:
        close = api_close_long(quantity_of_stock)
        if close:
            transition('to_order')
            print('Long position CLOSED due to opposite signal')

    elif stop:
        close = api_close_long(quantity_of_stock)
        if close:
            cooldown_now()
            transition('cooldown')
            print('Long position CLOSED due to stoploss')
    elif bail:
        close = api_close_long(quantity_of_stock)
        transition('to_order')
        if close:
            print('Bailout.')
    elif secure_profit:
        global fulfilled
        secure_quantity = int((quantity_of_stock / 2))
        close = api_close_long(secure_quantity)
        if close:
            quantity_of_stock = (quantity_of_stock - secure_quantity)
            fulfilled = True
            print('Secured profit on: ' + str(secure_quantity) + ' SPXL')
            secure_profit = False
    elif trail_stop:
        close = api_close_long(quantity_of_stock)
        if close:
            cooldown_now()
            transition('cooldown')
            print('Long position closed due to trailing stop')
    else:
        print("It is not time to close LONG position yet.")


def api_close_short(quantity):
    global id_order
    realtime_short = float(realtime_bid_short)
    realtime_short = str(realtime_short)

    short_response = requests.post('https://api.tradier.com/v1/accounts/<acc number>/orders',
                                   data={'class': 'equity', 'symbol': short, 'side': 'sell',
                                         'quantity': quantity,
                                         'type': 'limit', 'duration': 'day', 'price': realtime_short},
                                   headers={'Authorization': 'Bearer #apikey',
                                            'Accept': 'application/json'}
                                   )
    short_resp = short_response.json()
    id_order = short_resp['order']['id']
    status = short_resp['order']['status']
    if ensure_execution('close', 'short'):
        return True


def close_position_short():
    trade_manage(short)
    global quantity_of_stock
    global thirty_mins
    global bail
    global secure_profit
    global secure_quantity
    global trail_stop
    now = pd.Timestamp.now(tz='America/New_York').floor('1min')
    print("Current amount of stock is: " + str(quantity_of_stock) + " SPXU")
    print('Timer is: ' + str(thirty_mins))
    if predict == 0:
        timer()

    if now >= thirty_mins:
        if predict == 0:
            timer()
        if predict != 0:
            close = api_close_short(quantity_of_stock)
            if close:
                cooldown_now()
                transition('cooldown')
                print('Short position CLOSED due to timer')
    elif last_predicts.count(2) == 5:
        close = api_close_short(quantity_of_stock)
        if close:
            transition('to_order')
            print('Short position CLOSED due to opposite signal')
    elif stop:
        close = api_close_short(quantity_of_stock)
        if close:
            cooldown_now()
            transition('cooldown')
            print('Short position CLOSED due to stoploss')
    elif bail:
        close = api_close_short(quantity_of_stock)
        if close:
            transition('to_order')
            print('Bailout.')
    elif secure_profit:
        global fulfilled
        secure_quantity = int((quantity_of_stock / 2))
        close = api_close_short(secure_quantity)
        if close:
            quantity_of_stock = (quantity_of_stock - secure_quantity)
            fulfilled = True
            print('Secured profit on: ' + str(secure_quantity) + ' SPXU')
            secure_profit = False
    elif trail_stop:
        close = api_close_short(quantity_of_stock)
        if close:
            cooldown_now()
            transition('cooldown')
            print('Short position closed due to trailing stop')
    else:
        print("It is not time to close SHORT position yet.")


def reset():
    global secure_profit
    global fulfilled
    global stop
    global secure_quantity
    global start_trail
    global trail_stop
    global reference_price
    global dynamic_stop
    dynamic_stop = 0
    reference_price = 0
    trail_stop = False
    start_trail = False
    stop = False
    fulfilled = False
    secure_profit = False
    secure_quantity = 0


def create_position(lot):
    global id_order
    global quantity_of_stock
    global bet_size
    reset()
    realtime_short = float(realtime_ask_short)
    realtime_long = float(realtime_ask_long)
    realtime_long = str(realtime_long)
    realtime_short = str(realtime_short)


    if predict == 0:
        sizing()
        boll_bands('short')
        sized_bet = float(lot * bet_size)
        quantity_of_stock = int(sized_bet / realtime_ask_short)
        quantity_of_stock = str(quantity_of_stock)
        short_response = requests.post('https://api.tradier.com/v1/accounts/<acc number>/orders',
                                       data={'class': 'equity', 'symbol': short, 'side': 'buy',
                                             'quantity': quantity_of_stock,
                                             'type': 'limit', 'duration': 'day', 'price': realtime_short},
                                       headers={'Authorization': 'Bearer #apikey',
                                                'Accept': 'application/json'}
                                       )
        short_resp = short_response.json()
        id_order = short_resp['order']['id']
        status = short_resp['order']['status']
        if ensure_execution('open', 'short'):
            timer()
            transition('to_close_short')
            print('Short position CREATED with: ' + quantity_of_stock + " SPXU")
    if predict == 2:
        sizing()
        boll_bands('long')
        sized_bet = float(lot * bet_size)
        quantity_of_stock = int(sized_bet / realtime_ask_long)
        quantity_of_stock = str(quantity_of_stock)
        long_response = requests.post('https://api.tradier.com/v1/accounts/<acc number>/orders',
                                      data={'class': 'equity', 'symbol': long, 'side': 'buy',
                                            'quantity': quantity_of_stock,
                                            'type': 'limit', 'duration': 'day', 'price': realtime_long},
                                      headers={'Authorization': 'Bearer #apikey',
                                               'Accept': 'application/json'}
                                      )
        long_resp = long_response.json()
        id_order = long_resp['order']['id']
        status = long_resp['order']['status']
        if ensure_execution('open', 'long'):
            timer()
            transition('to_close_long')
            print('long position CREATED with: ' + quantity_of_stock + " SPXL")
    if predict == 1:
        print('No position created.')


def ensure_execution(order_type, side):
    global id_order
    id = str(id_order)
    endpoint_id = 'https://api.tradier.com/v1/accounts/<acc number>/orders/{}'.format(id)
    order_response = requests.get(endpoint_id,
                                  params={},
                                  headers={'Authorization': 'Bearer #apikey',
                                           'Accept': 'application/json'}
                                  )
    order_resp = order_response.json()
    if order_resp['order']['id'] == id_order:
        if order_resp['order']['status'] == 'filled':
            print('Executed at limit.')
            return True
        if order_resp['order']['status'] == 'open':
            modify_resp = requests.put(endpoint_id,
                                       data={'type': 'market', 'duration': 'day'},
                                       headers={'Authorization': 'Bearer #apikey',
                                                'Accept': 'application/json'}
                                       )
            try:
                modify = modify_resp.json()
                print('Executed at market.')
                return True
            except:
                json.decoder.JSONDecodeError
                print('Modify order error')
                return True


def timer():
    global thirty_mins
    time_now = pd.Timestamp.now(tz='America/New_York').floor('1min')
    thirty_mins = (time_now + pd.Timedelta('15min'))


def cooldown():
    global cool_start
    time_now = pd.Timestamp.now(tz='America/New_York').floor('1min')
    mins = (cool_start + pd.Timedelta('5min'))
    if time_now >= mins:
        transition('to_order')
        print('Transitioning back to order state.')
    else:
        time.sleep(60)
        print('Recently exited position, cooling down.')


def cooldown_now():
    global cool_start
    time_now = pd.Timestamp.now(tz='America/New_York').floor('1min')
    cool_start = time_now


def transition(new_state):
    global state
    state = new_state


def run(lot):
    global state
    if state == 'to_order':
        create_position(lot)
    if state == 'to_close_long':
        close_position_long()
    if state == 'to_close_short':
        close_position_short()
    if state == 'cooldown':
        cooldown()
    else:
        print('State: ' + str(state))

def check_market_status():
    response = requests.get('https://api.tradier.com/v1/markets/clock',
                            params={},
                            headers={'Authorization': 'Bearer #apikey',
                                     'Accept': 'application/json'}
                            )
    intraday_market_response = response.json()
    market_status = (intraday_market_response['clock']['state'])
    return market_status

def intraday_market_resp():
    response = requests.get('https://api.tradier.com/v1/markets/clock',
                            params={},
                            headers={'Authorization': 'Bearer #apikey',
                                     'Accept': 'application/json'}
                            )
    intraday_market_response = response.json()
    return intraday_market_response

def main(symbol, lot):
    global end_timer
    global session_id
    market_status = check_market_status()
    intraday_market_response = intraday_market_resp()
    end_timer = 0
    while True:
        while market_status == 'open':
            time.sleep(5)
            market_time = (intraday_market_response['clock']['timestamp'])
            build_x_data(symbol)
            prediction()
            market_time = datetime.datetime.fromtimestamp(market_time)
            end_time = market_time.replace(hour=12, minute=30, second=0)
            start_time = market_time.replace(hour=6, minute=40, second=0)
            begin = (market_time >= start_time)
            end = (market_time <= end_time)
            if market_time < start_time:
                print('Not time to start trading algorithm yet.')
                time.sleep(30)
            if begin & end:
                run(lot)
                intraday_market_response = intraday_market_resp()
            if market_time >= end_time:
                print('Finalizng day...')
                end_timer += 1
                bailout()
                intraday_market_response = intraday_market_resp()

        while market_status != 'open':
            time.sleep(60)
            market_status = check_market_status()
            print('Market not open. Status: ' + str(market_status))
            break
        #   gain_loss()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('symbol', type=str, default='SPY', help='symbol you want to trade')
    parser.add_argument('lot', type=int, default=2000, help='how much cash u tryna spend')
    arg = parser.parse_args()
    main_thread = threading.Thread(target=main, args=(arg.symbol, arg.lot))
    main_thread.start()
    stream_thread = threading.Thread(target=stream)
    stream_thread.daemon = True
    stream_thread.start()
