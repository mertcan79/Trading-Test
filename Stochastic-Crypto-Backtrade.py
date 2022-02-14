from datetime import datetime
import backtrader as bt
import quantstats
import requests
import pandas as pd
import yfinance as yf
import logging

def get_crypto_price(symbol, exchange, start_date = None):
    api_key = '2K4QSQOKP9MGKK1H'
    api_url = f'https://www.alphavantage.co/query?function=DIGITAL_CURRENCY_DAILY&symbol={symbol}&market={exchange}&apikey={api_key}'
    raw_df = requests.get(api_url).json()
    df = pd.DataFrame(raw_df['Time Series (Digital Currency Daily)']).T
    df = df.rename(columns = {'1a. open (USD)': 'open', '2a. high (USD)': 'high', '3a. low (USD)': 'low', '4a. close (USD)': 'close', '5. volume': 'volume'})
    for i in df.columns:
        df[i] = df[i].astype(float)
    df.index = pd.to_datetime(df.index)
    df = df.iloc[::-1].drop(['1b. open (USD)', '2b. high (USD)', '3b. low (USD)', '4b. close (USD)', '6. market cap (USD)'], axis = 1)
    if start_date:
        df = df[df.index >= start_date]
    return df

btc = get_crypto_price(symbol = 'BTC', exchange = 'USD', start_date = '2020-01-01')
btc.to_csv("btc.csv")
eth = get_crypto_price(symbol = 'ETH', exchange = 'USD', start_date = '2020-01-01')
eth.to_csv("eth.csv")


class StochasticSR(bt.Strategy):
    '''Trading strategy that utilizes the Stochastic Oscillator indicator for oversold/overbought entry points,
    and previous support/resistance via Donchian Channels as well as a max loss in pips for risk levels.'''
    # parameters for Stochastic Oscillator and max loss in pips
    # Donchian Channels to determine previous support/resistance levels will use the given period as well
    # http://www.ta-guru.com/Book/TechnicalAnalysis/TechnicalIndicators/Stochastic.php5 for Stochastic Oscillator formula and description
    params = (('period', 14), ('pfast', 3), ('pslow', 3), ('upperLimit', 80), ('lowerLimit', 20), ('stop_pips', .002))

    def __init__(self):
        '''Initializes logger and variables required for the strategy implementation.'''
        # initialize logger for log function (set to critical to prevent any unwanted autologs, not using log objects because only care about logging one thing)
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        logging.basicConfig(format='%(message)s', level=logging.CRITICAL, handlers=[
            logging.FileHandler("LOG.log"),
            logging.StreamHandler()
        ])

        self.order = None
        self.donchian_stop_price = None
        self.price = None
        self.stop_price = None
        self.stop_donchian = None

        self.stochastic = bt.indicators.Stochastic(self.data, period=self.params.period, period_dfast=self.params.pfast,
                                                   period_dslow=self.params.pslow,
                                                   upperband=self.params.upperLimit, lowerband=self.params.lowerLimit)

    def log(self, txt, doprint=True):
        '''logs the pricing, orders, pnl, time/date, etc for each trade made in this strategy to a LOG.log file as well as to the terminal.'''
        date = self.data.datetime.date(0)
        time = self.data.datetime.time(0)
        if (doprint):
            logging.critical(str(date) + ' ' + str(time) + ' -- ' + txt)

    def notify_trade(self, trade):
        '''Run on every next iteration, logs the P/L with and without commission whenever a trade is closed.'''
        if trade.isclosed:
            self.log('CLOSE -- P/L gross: {}  net: {}'.format(trade.pnl, trade.pnlcomm))

    def notify_order(self, order):
        '''Run on every next iteration, logs the order execution status whenever an order is filled or rejected,
        setting the order parameter back to None if the order is filled or cancelled to denote that there are no more pending orders.'''
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log('BUY -- units: 10000  price: {}  value: {}  comm: {}'.format(order.executed.price,
                                                                                      order.executed.value,
                                                                                      order.executed.comm))
                self.price = order.executed.price
            elif order.issell():
                self.log('SELL -- units: 10000  price: {}  value: {}  comm: {}'.format(order.executed.price,
                                                                                       order.executed.value,
                                                                                       order.executed.comm))
                self.price = order.executed.price
        elif order.status in [order.Rejected, order.Margin]:
            self.log('Order rejected/margin')

        self.order = None

    def stop(self):
        '''At the end of the strategy backtest, logs the ending value of the portfolio as well as one or multiple parameter values for strategy optimization purposes.'''
        self.log('(period {}) Ending Value: {}'.format(self.params.period, self.broker.getvalue()), doprint=True)

    def next(self):
        '''Checks to see if Stochastic Oscillator, position, and order conditions meet the entry or exit conditions for the execution of buy and sell orders.'''
        if self.order:
            # if there is a pending order, don't do anything
            return
        if self.position.size == 0:
            # When stochastic crosses back below 80, enter short position.
            if self.stochastic.lines.percD[-1] >= 80 and self.stochastic.lines.percD[0] <= 80:
                # stop price at last support level in self.params.period periods
                self.donchian_stop_price = max(self.data.high.get(size=self.params.period))
                self.order = self.sell()
                # stop loss order for max loss of self.params.stop_pips pips
                self.stop_price = self.buy(exectype=bt.Order.Stop, price=self.data.close[0] + self.params.stop_pips,
                                           oco=self.stop_donchian)
                # stop loss order for donchian SR price level
                self.stop_donchian = self.buy(exectype=bt.Order.Stop, price=self.donchian_stop_price,
                                              oco=self.stop_price)
            # when stochastic crosses back above 20, enter long position.
            elif self.stochastic.lines.percD[-1] <= 20 and self.stochastic.lines.percD[0] >= 20:
                # stop price at last resistance level in self.params.period periods
                self.donchian_stop_price = min(self.data.low.get(size=self.params.period))
                self.order = self.buy()
                # stop loss order for max loss of self.params.stop_pips pips
                self.stop_price = self.sell(exectype=bt.Order.Stop, price=self.data.close[0] - self.params.stop_pips,
                                            oco=self.stop_donchian)
                # stop loss order for donchian SR price level
                self.stop_donchian = self.sell(exectype=bt.Order.Stop, price=self.donchian_stop_price,
                                               oco=self.stop_price)

        if self.position.size > 0:
            # When stochastic is above 70, close out of long position
            if (self.stochastic.lines.percD[0] >= 70):
                self.close(oco=self.stop_price)
        if self.position.size < 0:
            # When stochastic is below 30, close out of short position
            if (self.stochastic.lines.percD[0] <= 30):
                self.close(oco=self.stop_price)

class BBADX(bt.Strategy):
    '''Mean Reversion trading strategy that utilizes Bollinger Bands for signals and ADX for locating and avoiding trends'''

    # Parameters that can be optimized for best performance for different markets or candlestick timeframes
    params = (('BB_MA', 20), ('BB_SD', 2), ('ADX_Period', 14), ('ADX_Max', 40))

    def __init__(self):
        '''Initializes all variables to be used in this strategy'''
        self.order = None
        self.stopprice = None
        self.closepos = None
        self.adx = bt.indicators.AverageDirectionalMovementIndex(self.data, period=self.params.ADX_Period)
        self.bb = bt.indicators.BollingerBands(self.data, period=self.params.BB_MA, devfactor=self.params.BB_SD)

    def log(self, txt, doprint=True):
        '''Logs any given text with the time and date as long as doprint=True'''
        date = self.data.datetime.date(0)
        time = self.data.datetime.time(0)
        if doprint:
            print(str(date) + ' ' + str(time) + '--' + txt)

    def notify_order(self, order):
        '''Run on every next iteration. Checks order status and logs accordingly'''
        if order.status in [order.Submitted, order.Accepted]:
            return
        elif order.status == order.Completed:
            if order.isbuy():
                self.log('BUY   price: {}, value: {}, commission: {}'.format(order.executed.price, order.executed.value,
                                                                             order.executed.comm))
            if order.issell():
                self.log(
                    'SELL   price: {}, value: {}, commission: {}'.format(order.executed.price, order.executed.value,
                                                                         order.executed.comm))
        elif order.status in [order.Rejected, order.Margin]:
            self.log('Order Rejected/Margin')

        # change order variable back to None to indicate no pending order
        self.order = None

    def notify_trade(self, trade):
        '''Run on every next iteration. Logs data on every trade when closed.'''
        if trade.isclosed:
            self.log('CLOSE   Gross P/L: {}, Net P/L: {}'.format(trade.pnl, trade.pnlcomm))

    def stop(self):
        '''Runs at the end of the strategy. Logs parameter values and ending value for optimization. Exports data to csv file created in run.py.'''
        self.log('(bbma: {}, bbsd: {}, adxper: {}) Ending Value: {}'.format(self.params.BB_MA, self.params.BB_SD,
                                                                            self.params.ADX_Period,
                                                                            self.broker.getvalue()), doprint=True)
        fields = [[self.params.BB_MA, self.params.BB_SD, self.params.ADX_Period, self.broker.getvalue()]]
        df = pd.DataFrame(data=fields)
        df.to_csv('optimization.csv', mode='a', index=False, header=False)

    def next(self):
        '''Runs for every candlestick. Checks conditions to enter and exit trades.'''
        if self.order:
            return

        if self.position.size == 0:
            if self.adx[0] < self.params.ADX_Max:
                if (self.data.close[-1] > self.bb.lines.top[-1]) and (self.data.close[0] <= self.bb.lines.top[0]):
                    self.order = self.sell()
                    self.stopprice = self.bb.lines.top[0]
                    self.closepos = self.buy(exectype=bt.Order.Stop, price=self.stopprice)

                elif (self.data.close[-1] < self.bb.lines.bot[-1]) and (self.data.close[0] >= self.bb.lines.bot[0]):
                    self.order = self.buy()
                    self.stopprice = self.bb.lines.bot[0]
                    self.closepos = self.sell(exectype=bt.Order.Stop, price=self.stopprice)

        elif self.position.size > 0:
            if (self.data.close[-1] < self.bb.lines.mid[-1]) and (self.data.close[0] >= self.bb.lines.mid[0]):
                self.closepos = self.close()
        elif self.position.size < 0:
            if (self.data.close[-1] > self.bb.lines.mid[-1]) and (self.data.close[0] <= self.bb.lines.mid[0]):
                self.closepos = self.close()

cerebro = bt.Cerebro()
cerebro.broker.setcash(100000.0)
#data = bt.feeds.CCXT(exchange="binance", symbol='BNB/USDT', name="1m",timeframe=bt.TimeFrame.Minutes, fromdate=hist_start_date,compression=1)
data1 = bt.feeds.GenericCSVData(
    dataname='btc.csv',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2022, 1, 1),
    nullvalue=0.0,
    dtformat=('%Y-%m-%d'),
    datetime=0,
    high=2,
    low=3,
    open=1,
    close=4,
    volume=5,
    openinterest=-1,
    timeframe=bt.TimeFrame.Days
)
data2 = bt.feeds.GenericCSVData(
    dataname='eth.csv',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2022, 1, 1),
    nullvalue=0.0,
    dtformat=('%Y-%m-%d'),
    datetime=0,
    high=2,
    low=3,
    open=1,
    close=4,
    volume=5,
    openinterest=-1
)
#data1 = bt.feeds.PandasData(dataname=yf.download('AMD ', '2019-01-01', '2022-01-01', auto_adjust=True))
#data2 = bt.feeds.PandasData(dataname=yf.download('MSFT ', '2019-01-01', '2022-01-01', auto_adjust=True))
cerebro.adddata(data1)
#cerebro.adddata(data2)
cerebro.broker.setcommission(commission=0.001)
cerebro.addstrategy(StochasticSR)
cerebro.addanalyzer(bt.analyzers.PyFolio, _name='PyFolio')

start_portfolio_value = cerebro.broker.getvalue()
results = cerebro.run()
strat = results[0]
end_portfolio_value = cerebro.broker.getvalue()
pnl = end_portfolio_value - start_portfolio_value

print(f'Starting Portfolio Value: {start_portfolio_value:2f}')
print(f'Final Portfolio Value: {end_portfolio_value:2f}')
print(f'PnL: {pnl:.2f}')

portfolio_stats = strat.analyzers.getbyname('PyFolio')
returns, positions, transactions, gross_lev = portfolio_stats.get_pf_items()
returns.index = returns.index.tz_convert(None)
quantstats.reports.html(returns, output='stats.html', title='BTC Sentiment')
cerebro.plot(iplot=False)
