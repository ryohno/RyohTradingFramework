# RyohTrader

Trading framework using a pickled prediction model, utilizing Tradier Brokerage API. As I became interested in trading, I built a prediction model and this framework from scratch as my first real programming project. RyohTrader has two threads: the stream() thread for realtime data from a WebSockets connection, and main() for execution and trade management. This framework is specifically built to trade the leveraged SPY ETFs of SPXU (for short positions) and SPXL (for long positions), using a strategy of time varying beta. 

## main()

Taking the symbol (in this case SPY) and lot size as inputs, main() sets the overall logic of the trading bot. Calls the check_market_status() function, which returns the current state of the market. If it is not open, it sleeps for 60 seconds. If open, it calls: 
```python
build_x_data(symbol)
prediction()
```
These two functions form the basis of making predictions in the bot. The first makes an request to the Tradier API, receiving data from the past for time, volume, and OHLC prices. It stores this data in a Pandas Dataframe, which is used by the prediction() function. Passing the data through the model, it returns the prediction and probability. 

Three conditions in the 'open' market status are set: before bot start time, run bot time, and end of day. While before the start time for the bot, no actions are taken. During run time, it calls the run() function which sets in motion the chain of events for creating, managing, and exiting positions. After bot end time, it is switched to the bailout() function, similar to the run() function, but exits the loops when no positions are active. 

## stream()

```python
def stream():
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
        asyncio.get_event_loop().run_until_complete(connect_and_consume())
    except:
        websockets.WebSocketException
        print('Stream failed, reconnecting.')
        stream()

```

Sets the realtime datastream (via websockets) in an asyncio loop which runs concurrently in a different thread. Wrapped in a try-except block, if the connection fails, it immediately re-calls the function stream() in order to reconnect. The data passed from the websockets connection is immediately assigned to realtime_bid_short/long and realtime_ask_short/long variables for realtime, updated use in execution and management. 


## Trading States

This bot is managed by four states: 'to_order', 'to_close_long', 'to_close_short', and 'cooldown', used in the run() function. 
####
```python
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
```
In the 'to_order' state, the create_position function is called with lot as a variable. It remains in this state unless a position is created, and depending on the direction (long/short), it will switch to its respective closing state. When a position is closed, it will 'cooldown' for a specified amount of time, in order to prevent refiring on outdated signals. 

## Creating a Position
When creating a position, the reset() function is called to reset global variables into their original position. Using creating a long position as an example: 

```python
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

```
The sizing() function sizes the function based off class probability defined during prediction(). Boll_bands('long') sets the dynamic target for take profit, and sets the dynamic stop loss. Setting a dynamic stop-loss and take-profit is important to adjust for changing market conditions. For this, one could replace Bollinger Band use with ATR. Using the realtime price and the percentage sized bet, an order for # of stock is sent to the Tradier API. The order of the ID is stored in the id_order variable, and execution is ensured via the ensure_execution function. If the order is filled, the function returns true, and the timer is started for one of the variables of position management. The state is then transitioned to a 'to_close_long' state.

## Closing a Position
```python
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
```
Continuing from the example of a long position, this function checks if any of the closing conditions are met. If the prediction returns '2' (for long) again, the timer is reset. Closing conditions include: hard timer, a defined rolling window of opposite predictions (to ensure against a false negative), stoploss, bailout during end of day, securing profit when target is hit (this does NOT transition state, but begins a trail stop), or trail stop is met. 

## Future

The use of global variables is bad practice and jarring. In future, I would make modifications to make the script more modular with classes and in different files, add config files for different tickers, and reduce the usage of globals and instead pass more data into the functions themselves. This project has taught me basics of Python, increased understanding of Pandas Dataframes, taught REST API and websockets usage, and the basics of statistics and data science in building my prediction model. 


