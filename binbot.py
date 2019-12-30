"""
Binance Trading Bot
"""

from binance.client import Client
from datetime import datetime
import time
import numpy
import talib

api_key = ""
api_secret = ""
client = Client(api_key, api_secret)

asset = "BTC"; base = "USDT"
interval_mins = 30 # [3, 240]

class Portfolio:
    def __init__(self, candle, positions, funds):
        self.ts = candle['ts_end']
        self.asset = positions['asset'][1]
        self.base = positions['base'][1]
        self.price = candle['close']
        self.position_value = self.price * self.asset
        self.size = self.base + self.position_value
        self.funds = funds
        if funds > self.size or funds == 0: self.funds = float(self.size)
        self.sizeT = float(self.funds)
        self.rin = self.price * self.asset / self.size
        self.rinT = self.price * self.asset / self.sizeT

class Instance:
    def __init__(self, asset, base, interval_mins):
        self.ticks = 0; self.days = 0
        self.params = self.get_params()
        #self.get_seeds()
        #self.update_f()

        self.exchange = "binance"
        self.asset = str(asset); self.base = str(base)
        self.pair = self.asset + self.base
        self.interval = int(interval_mins)
        print("New trader instance started on {} {}m.".format(self.pair, self.interval))

        print("Getting historical candles...")
        self.candles_raw = self._candles_raw_init()
        self.candles = self._candles_init(self.candles_raw)
        self.candles_raw = self.shrink_list(self.candles_raw, 2*self.interval)
        self.candles_raw_unused = self._get_raw_unused()
        print("Historical candles loaded.")

        self.deposits = dict()
        self.withdrawals = dict()
        self.deposits_pending = set()
        self.withdrawals_pending = set()
        self.earliest_pending = 0

        self.positions = self.get_positions()
        p = Portfolio(self.candles[-1], self.positions, float(self.params['funds']))
        self.last_order = {"type": "none", "amt": 0, "pt": self.candles[-1]['close']}
        self.signal = {"rinTarget": p.rinT, "rinTargetLast": p.rinT, "position": "none", "status": 0, "apc": p.price, "target": p.price, "stop": p.price}

    def _candles_raw_init(self) -> list:
        """ Get enough 1m data to compile 600 historical candles """
        data = self.get_historical_candles_method(self.pair, "1m", "{} minutes ago UTC".format(600*self.interval))
        for i in range(self.interval - 1): data.pop()
        for i in range(len(data)): data[i] = self.get_candle(data[i])
        return data

    def _candles_init(self, candles_raw) -> list:
        # Compile the 1m candles_raw into 30m candles
        candles = list()
        candle_new = dict()
        for i in range(len(candles_raw)):
            order = (i + 1) % self.interval
            # [1, 2, ..., interval - 1, 0, 1, 2, ...]
            candle_raw = candles_raw[len(candles_raw) - 1 - i]
            # Going backwards through candles_raw to have control over how long
            # until next candle

            if order == 1:
                candle_new = candle_raw
                continue

            if candle_raw["high"] > candle_new["high"]:
                candle_new["high"] = candle_raw["high"]
            if candle_raw["low"] < candle_new["low"]:
                candle_new["low"] = candle_raw["low"]
            candle_new["volume"] += candle_raw["volume"]

            if order == 0:
                candle_new["open"] = candle_raw["open"]
                candle_new["ts_start"] = candle_raw["ts_start"]
                candles.append(candle_new)

        return candles[::-1]

    def _get_raw_unused(self) -> int:
        # Update candles_raw with recent 1m candles
        # Return how many 1m candles were imported
        raw_unused = -1
        str_out = str()
        data = self.get_historical_candles_method(self.pair, "1m", "{} minutes ago UTC".format(2*self.interval))
        data.pop()
        for i in range(len(data)):
            candle_raw = self.get_candle(data[i])
            if raw_unused > -1:
                raw_unused += 1
            if candle_raw["ts_end"] == self.candles[-1]["ts_end"]:
                raw_unused += 1
                continue

            if raw_unused > 0:
                self.candles_raw.append(candle_raw)
                str_out += "~ {}\n".format(candle_raw)

        print("{} current 1m candles.".format(raw_unused))
        print(str_out[:-1])
        return raw_unused

    def get_historical_candles_method(self, symbol, interval, start_str) -> list:
        # Get historical candles without connection problems breaking the program
        while True:
            try:
                data = client.get_historical_klines(symbol, interval, start_str)
                break
            except Exception as e:
                print("Error:", e)
                print("Sleeping for 2 seconds and then retrying.")
                time.sleep(2)
        return data

    def shrink_list(self, list_in, size) -> list:
        if len(list_in) > size: return list_in[-size:]
        return list_in

    def get_candle(self, data) -> dict:
        # data is a kline list from Binance
        candle = {
            "ts_start": int(data[0]),
            "open": float(data[1]),
            "high": float(data[2]),
            "low": float(data[3]),
            "close": float(data[4]),
            "volume": float(data[5]),
            "ts_end": int(data[6])
        }
        return candle

    #def init_storage(self, p):
    #    print("~~ init storage ~~")

    def init(self):
        print("~~ init ~~")

    def strat(self, p):
        """ strategy / trading algorithm
        - Use talib for indicators
        - Talib objects require numpy.array objects as input
        - rinTarget stands for 'ratio invested target'
        - Set s['rinTarget'] between 0 and 1. 0 is 0%, 1 is 100% invested
        """
        print("~~ trading strategy ~~")
        s = self.signal

        print("Most recent candle:", self.candles[-1])
        print("Positions:", self.positions)

        close_data = numpy.array([c['close'] for c in self.candles])
        mas = round(talib.SMA(close_data, timeperiod = 20)[-1], 8)
        mal = round(talib.SMA(close_data, timeperiod = 100)[-1], 8)

        print("20 SMA:", mas)
        print("100 SMA:", mal)

        s['rinTarget'] = 1
        if mas > mal: s['rinTarget'] = 0

        print("rinTarget:", s['rinTarget'], "s['rinTargetLast']", s['rinTargetLast'])

    def bso(self, p):
        """ buy/sell/other """
        print("~~ buy/sell/other ~~")
        s = self.signal

        rbuy = s['rinTarget'] - s['rinTargetLast']
        order_size = 0
        if rbuy * p.asset >= 0:
            order_size = abs(rbuy * p.funds)
            if order_size > p.base: order_size = p.base
        if rbuy * p.asset < 0:
            rbuy_asset = rbuy / s['rinTargetLast']
            order_size = abs(rbuy_asset * p.asset * p.price)
        if order_size < self.min_order: order_size = 0

        if order_size > 0:
            if rbuy > 0: pt = (1 + 0.0015) * p.price
            else: pt = (1 - 0.0015) * p.price
            pt = round(pt, self.pt_dec)
            if rbuy > 0: amt = order_size / pt
            else: amt = order_size / p.price
            amt = round(0.995*amt*10**self.amt_dec - 2)/10**self.amt_dec
            if rbuy > 0: self.limit_buy(amt, pt)
            if rbuy < 0: self.limit_sell(amt, pt)
        if rbuy == 0: order_size = 0
        if order_size == 0:
            if self.ticks == 1: print("Waiting for a signal to trade...")
            self.last_order = {"type": "none", "amt": 0, "pt": p.price}

    def limit_buy(self, amt, pt):
        try:
            print("buy amt", amt, "pt", pt, "prod", amt * pt)
            self.last_order = {"type": "buy", "amt": amt, "pt": pt}
            client.order_limit_buy(symbol = self.pair, quantity = amt, price = pt)
        except Exception as e:
            print("Error buying. '{}'".format(e))

    def limit_sell(self, amt, pt):
        try:
            print("sell amt", amt, "pt", pt, "prod", amt * pt)
            self.last_order = {"type": "sell", "amt": amt, "pt": pt}
            client.order_limit_sell(symbol = self.pair, quantity = amt, price = pt)
        except Exception as e:
            print("Error buying. '{}'".format(e))

    def get_dwts(self, diffasset, diffbase):
        # get end of previous candle, initialize vars
        l = self.last_order
        s = self.signal
        ts_last = self.candles[-2]['ts_end']
        ts = self.earliest_pending
        diffasset_expt = 0.0
        diffbase_expt = 0.0

        if self.ticks == 1: # first tick
            # get all pending dws from previous week
            deposits = client.get_deposit_history(startTime = ts - 1000*60*60*24*7)['depositList']
            withdrawals = client.get_withdraw_history(startTime = ts - 1000*60*60*24*7)['withdrawList']
            # filter for asset, remove completed orders
            deposits = [d for d in deposits if d['asset'] in {asset, base} and d['status'] < 1]
            withdrawals = [w for w in withdrawals if w['asset'] in {asset, base} and w['status'] < 0]

            # Initialize deposits, deposits_pending, withdrawals, withdrawals_pending, earliest_pending
            for deposit in deposits:
                id = deposit['txId']
                self.deposits[id] = deposit
                self.deposits_pending.add(id)
                if deposit['insertTime'] < self.earliest_pending:
                    self.earliest_pending = deposit['insertTime']
            for withdrawal in withdrawals:
                id = withdrawal['id']
                self.withdrawals[id] = withdrawal
                self.withdrawals_pending.add(id)
                if withdrawal['applyTime'] < self.earliest_pending:
                    self.earliest_pending = withdrawal['applyTime']

        else: # not first tick
            # get all dws starting from 1 s before the earliest pending dw
            deposits = client.get_deposit_history(startTime = ts - 1000)['depositList']
            withdrawals = client.get_withdraw_history(startTime = ts - 1000)['withdrawList']
            # filter for asset
            deposits = [d for d in deposits if d['asset'] in {asset, base}]
            withdrawals = [w for w in withdrawals if w['asset'] in {asset, base}]

            # check if pending dws have been completed then process them
            for deposit in deposits:
                id = deposit['txId']
                if id in self.deposits_pending:
                    if deposit['status'] > 0:
                        print("Deposit processed")
                        amt = deposit['amount']
                        if deposit['asset'] == base: diffbase_expt += amt
                        else: diffasset_expt += amt
                        self.deposits[id] = deposit
                        self.deposits_pending.remove(id)
            for withdrawal in withdrawals:
                id = withdrawal['id']
                if id in self.withdrawals_pending:
                    if withdrawal['status'] > 3:
                        print("Withdrawal processed")
                        amt = withdrawal['amount'] + withdrawal['transactionFee']
                        if withdrawal['asset'] == base: diffbase_expt -= amt
                        else: diffasset_expt -= amt
                        self.withdrawals[id] = withdrawal
                        self.withdrawals_pending.remove(id)

            # check if any dws have been added in the last candle
            deposits = [d for d in deposits if d['insertTime'] > ts_last]
            withdrawals = [w for w in withdrawals if w['applyTime'] > ts_last]

            # add new dws to pending if pending or process them
            for deposit in deposits:
                id = deposit['txId']
                self.deposits[id] = deposit
                if deposit['status'] < 1: self.deposits_pending.add(id)
                else:
                    print("Deposit processed")
                    amt = deposit['amount']
                    if deposit['asset'] == base: diffbase_expt += amt
                    else: diffasset_expt += amt
            for withdrawal in withdrawals:
                id = withdrawal['id']
                self.withdrawals[id] = withdrawal
                if withdrawal['status'] < 0: self.withdrawals_pending.add(id)
                else:
                    print("Withdrawal processed")
                    amt = withdrawal['amount'] + withdrawal['transactionFee']
                    if withdrawal['asset'] == base: diffbase_expt -= amt
                    else: diffasset_expt -= amt

        print("self.deposits:")
        for id in self.deposits: print("    ~", id + ":", self.deposits[id])
        print("self.deposits_pending: ", self.deposits_pending)
        print("self.withdrawals:")
        for id in self.withdrawals: print("    ~", id + ":", self.withdrawals[id])
        print("self.withdrawals_pending: ", self.withdrawals_pending)
        print("self.earliest_pending: ", self.earliest_pending)

        # Get trades
        trades = reversed(client.get_my_trades(symbol = self.pair, limit = 20))
        trades = [t for t in trades if t['time'] > ts_last]

        # process trades
        diffasset_trad = 0
        diffbase_trad = 0
        if len(trades) > 0:
            print("{} new trade(s) found.".format(len(trades)))
            for trade in trades:
                print("~", trade)
                qty = float(trade['qty'])
                price = float(trade['price'])
                if not trade['isBuyer']: qty *= -1
                diffasset_trad += qty
                diffbase_trad -= qty * price
                diffasset_expt += qty
                diffbase_expt -= qty * price

        rbuy = s['rinTarget'] - s['rinTargetLast']
        rTrade = 0
        if l['amt'] != 0: rTrade = abs(diffasset_trad / l['amt'])
        if diffasset_trad > 0:
            print("Buy detected")
            print("diffasset_trad", diffasset_trad, "l['amt']", l['amt'])
            print("rTrade", rTrade)
            if l['type'] != "buy":
                print("Manual buy detected.")
                rTrade = 0
            elif abs(rTrade - 1) > 0.1:
                print("Buy order partially filled.")
        elif diffasset_trad < 0:
            print("Sell detected")
            print("diffasset_trad", diffasset_trad, "l['amt']", l['amt'])
            print("rTrade", rTrade)
            if l['type'] != "sell":
                print("Manual sell detected")
                rTrade = 0
            elif abs(rTrade - 1) > 0.1:
                print("Sell order partially filled.")
        s['rinTargetLast'] += rTrade * rbuy

        # get unknown changes
        diffasset_expt = round(diffasset_expt, 8)
        diffbase_expt = round(diffbase_expt, 8)
        diffasset_unkn = diffasset - diffasset_expt
        diffbase_unkn = diffbase - diffbase_expt

        # process unknown changes
        if diffasset_unkn > 0: print(diffasset_unkn, self.asset, "has become available.")
        elif diffasset_unkn < 0: print(-diffasset_unkn, self.asset, "has become unavailable.")
        if diffbase_unkn > 0: print(diffbase_unkn, self.base, "has become available.")
        elif diffbase_unkn < 0: print(-diffbase_unkn, self.base, "has become unavailable.")

        # log outputs
        print("diffasset", diffasset)
        print("diffasset_expt", diffasset_expt)
        print("diffasset_unkn", diffasset_unkn)
        print("diffbase", diffbase)
        print("diffbase_expt", diffbase_expt)
        print("diffbase_unkn", diffbase_unkn)

        return

    def get_positions(self) -> dict:
        """ Get balances and check dwts """
        print("~~ get_positions ~~")
        # get balances
        positions = {"asset": [self.asset, 0], "base": [self.base, 0]}
        data = client.get_account()
        data = data["balances"]
        for i in range(len(data)):
            asset = data[i]["asset"]
            if asset not in {self.asset, self.base}: continue
            free = float(data[i]["free"])
            locked = float(data[i]["locked"])
            total = free + locked
            if asset == self.asset: positions['asset'][1] = total
            if asset == self.base: positions['base'][1] = total

        # return positions if init
        try:
            diff_asset = round(positions['asset'][1] - self.positions['asset'][1], 8)
            diff_base = round(positions['base'][1] - self.positions['base'][1], 8)
        except:
            ts = round(1000*time.time())
            self.earliest_pending = ts
            return positions

        # check for dwts before returning positions
        self.get_dwts(diff_asset, diff_base)
        return positions

    def get_params(self):
        # import config.txt
        params = dict()
        with open("config.txt") as cfg:
            par = [l.split()[0] for l in cfg.read().split("\n")[2:-1]]
            for p in par:
                p = p.split("=")
                if len(p) != 2: continue
                params[str(p[0])] = str(p[1])

        # check values
        funds = float(params['funds'])
        if funds < 0:
            print("Warning! Maximum amount to invest should be greater than zero.")
            params['funds'] = "0"

        # handle init case
        try:
            keys_old = {key for key in self.params}
            keys_new = {key for key in params}
        except:
            return params

        # check for added, removed, and changed params
        keys_added = {key for key in keys_new if key not in keys_old}
        keys_removed = {key for key in keys_old if key not in keys_new}

        if len(keys_added) > 0:
            print(len(keys_added), "parameter(s) added.")
            for key in keys_added: print("~", key, params[key])
        if len(keys_removed) > 0:
            print(len(keys_removed), "parameter(s) removed.")
            for key in keys_removed: print("~", key)

        keys_remaining = {key for key in keys_old if key in keys_new}
        keys_changed = set()

        for key in keys_remaining:
            if params[key] != self.params[key]: keys_changed.add(key)
        if len(keys_changed) > 0:
            print(len(keys_changed), "parameter(s) changed.")
            for key in keys_changed: print("~", key, self.params[key], params[key])

        return params

    def close_orders(self):
        orders = client.get_open_orders(symbol = self.pair)
        for order in orders:
            client.cancel_order(symbol = self.pair, orderId = order['orderId'])

    def ping(self):
        """ Check for and handle a new candle """
        # New raw candle?
        data = self.get_historical_candles_method(self.pair, "1m", "{} minutes ago UTC".format(2))
        data_top = self.get_candle(data[0])
        if data_top["ts_end"] != self.candles_raw[-1]["ts_end"]:
            self.candles_raw_unused += 1
            self.candles_raw.append(data_top)
            self.candles_raw = self.candles_raw[-2*self.interval:]

        # New candle?
        if self.candles_raw_unused == self.interval:
            # new candle / new tick
            print(40*"=", "tick", 40*"=")
            self.close_orders()
            self.ticks += 1
            self.days = (self.ticks - 1) * self.interval / (60 * 24)
            self.params = self.get_params()

            # get the new candle
            candle_new = dict()
            for i in range(self.interval):
                candle_raw = self.candles_raw[-1 - i]

                if i == 0:
                    candle_new = candle_raw
                    continue

                if candle_raw["high"] > candle_new["high"]:
                    candle_new["high"] = candle_raw["high"]
                if candle_raw["low"] < candle_new["low"]:
                    candle_new["low"] = candle_raw["low"]
                candle_new["volume"] += candle_raw["volume"]

                if i == self.interval - 1:
                    candle_new["open"] = candle_raw["open"]
                    candle_new["ts_start"] = candle_raw["ts_start"]
                    self.candles.append(candle_new)
                    self.candles_raw_unused = 0
                    self.candles = self.shrink_list(self.candles, 5000)

            # get portfolio
            data = client.get_symbol_info(self.pair)['filters']
            min_order = float(data[2]['minQty'])*self.candles[-1]['close']
            self.min_order = 3*max(min_order, float(data[3]['minNotional']))
            amt_dec = 8
            for char in reversed(data[2]['stepSize']):
                if char == "0": amt_dec -= 1
                else: break
            self.amt_dec = amt_dec
            pt_dec = 8
            for char in reversed(data[0]['tickSize']):
                if char == "0": pt_dec -= 1
                else: break
            self.pt_dec = pt_dec

            self.positions = self.get_positions()
            p = Portfolio(self.candles[-1], self.positions, float(self.params['funds']))

            # trading strategy, buy/sell/other
            self.strat(p)
            self.bso(p)

ins = Instance(asset, base, interval_mins)
ins.init()

while True:
    ins.ping()
    time.sleep(2)
