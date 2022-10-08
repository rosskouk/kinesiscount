"""Importer for Kinesis

This imports transactions found in the exportable CoinTracker CSV statement
available on kinesis.money
"""

import csv
from datetime import timezone
import datetime
import re
import logging
from os import path
import hmac
import hashlib
import requests
import json

from dateutil.parser import parse

from beancount.core.number import D
from beancount.core.number import ZERO
from beancount.core import data
from beancount.core import account
from beancount.core import amount
from beancount.core import position
from beancount.ingest import importer


class KinesisApi:
    def __init__(self, pub_key, pri_key, base_url):
        self.public_key = pub_key
        self.private_key = pri_key
        self.base_url = base_url  # https://client-api.kinesis.money

    def getNonce(self):
        dt = datetime.datetime.now(timezone.utc)
        utc_time = dt.replace(tzinfo=timezone.utc)
        utc_timestamp = round(utc_time.timestamp() * 1000)

        return str(utc_timestamp)

    def getAuthHeader(self, method, url, content=''):
        nonce = self.getNonce()
        message = str(nonce) + str(method) + str(url) + str(content)
        message = message.encode(encoding='UTF-8', errors='strict')

        byte_key = bytes(self.private_key, 'UTF-8')
        xsig = hmac.new(byte_key, message, hashlib.sha256).hexdigest().upper()

        headers = {
            "x-nonce": nonce,
            "x-api-key": self.public_key,
            "x-signature": xsig
        }

        if method != 'DELETE':
            headers["Content-Type"] = "application/json"

        return headers

    def getOHLC(self, pair, fromDate='2022-01-01T00:00:00.000Z', toDate='2022-03-31T00:00:00.000Z', timeFrame='60'):
        url = '/v1/exchange/ohlc/' + pair
        headersAuth = self.getAuthHeader('GET', url)

        payload = {
            'timeFrame': timeFrame,
            'fromDate': fromDate,
            'toDate': toDate
        }

        try:
            response = requests.get(self.base_url + url, headers=headersAuth, params=payload)

        except:
            return response

        return json.loads(response.text)

    def getPrice(self, pair):

        url = '/v1/exchange/mid-price/' + pair
        headersAuth = self.getAuthHeader('GET', url)

        try:
            response = requests.get(self.base_url + url, headers=headersAuth)
        except:
            return response

        return response


class Importer(importer.ImporterProtocol):
    """An importer for Kinesis CoinTracker CSV files"""

    def __init__(self,
                 acct_account_root,
                 acct_expenses_root,
                 acct_uncategorised_txn,
                 api_public_key,
                 api_private_key,
                 api_url
                 ):
        self.account_root = acct_account_root
        self.expenses_root = acct_expenses_root
        self.uncategorised_txn = acct_uncategorised_txn
        self.api_public_key = api_public_key
        self.api_private_key = api_private_key
        self.api_url = api_url

    def identify(self, file):
        # Match if the filename is as downloaded and the header has the unique
        # fields combination we're looking for.
        return (re.match(r"Account balance_Statement_KM13451730_.*\.csv", path.basename(file.name)) and
                re.match("DateTime,HIN,Currency_Code,Transaction_Type,Transaction_ID,Order_ID,Currency_Pair,Amount,Trade_Price,Total,Fee,Fee_Currency,Trade_Value,Trade_Value_Currency,Starting_Balance,Starting_Balance_Currency,Closing_Balance,Closing_Balance_Currency", file.head()))

    def file_name(self, file):
        return f'kinesis.{path.basename(file.name)}'

    def file_account(self, _):
        return self.account_root

    def extract(self, file):
        # Open the CSV file and create directives.
        entries = []
        index = 0
        with open(file.name) as infile:
            for index, row in enumerate(csv.DictReader(infile)):
                meta = data.new_metadata(file.name, index)
                date = parse(row['DateTime']).date()
                rtype = row['Transaction_Type']
                link = f'{row["Transaction_ID"]}'
                fees = amount.Amount(D(row['Fee']), row['Fee_Currency'])

                if rtype == 'Trade_Buy' and row['Currency_Code'] in ['KAU', 'KAG', 'KVT']:
                    # Get the source buy currency
                    currency_pair = row['Currency_Pair'].split('_')
                    bought_currency = currency_pair[0]
                    sold_currency = currency_pair[1]

                    # Extract transaction details
                    bought_units = amount.Amount(D(row['Amount']), bought_currency)
                    sold_units = amount.Amount(D(row['Total'].replace(',', '')), sold_currency)

                    # Amount left after subtracting fees
                    retained_units = amount.Amount(D((bought_units.number - fees.number)), bought_currency)

                    # Calculate the rate
                    rate = round(D(sold_units.number / bought_units.number), 5)

                    # Generate account names
                    instrument_account = account.join(self.account_root, bought_currency, sold_currency)
                    fiat_account = account.join(self.account_root, sold_currency)
                    fee_account = account.join(self.expenses_root, bought_currency, 'Transaction-Fee')

                    # Generate the description
                    desc = f'Kinesis buy {bought_currency} for {sold_currency}'

                    cost = position.Cost(rate, sold_currency, None, None)

                    txn = data.Transaction(
                        meta, date, self.FLAG, None, desc, data.EMPTY_SET, {link}, [
                            data.Posting(fiat_account, -sold_units, None, None, None, None),
                            data.Posting(fee_account, fees, cost, None, None, None),
                            data.Posting(instrument_account, retained_units, cost, None, None, None)
                        ])

                elif rtype == 'Trade_Buy' and row['Currency_Code'] not in ['KAU', 'KAG', 'KVT']:
                    # Duplicate line in CSV, ignore
                    continue

                elif rtype == 'Withdrawal':
                    # Ignore withdrawls, these will be picked up by the destination account statement
                    continue

                elif rtype == 'Deposit':
                    # Ignore deposits, this will be picked up on the source account statement
                    continue

                elif rtype in ['Holders_Distribution', 'Holders_Yield_Distribution_Adjustment', 'Velocity_Distribution']:
                    assert fees.number == ZERO

                    # Generate account names
                    source_account = account.join('Income:M', row['Currency_Code'], 'Yields')
                    destination_account = account.join(self.account_root, row['Currency_Code'], 'Yields')

                    # Extract transaction details
                    deposited_units = amount.Amount(D(row['Amount']), row['Currency_Code'])

                    # Create a currency pair for price tracking
                    currency_pair = f"{row['Currency_Code']}_GBP"

                    # Format date for price lookup
                    from_date = f'{date.strftime("%Y-%m-%d")}T00:00:00.000Z'
                    to_date = f'{date.strftime("%Y-%m-%d")}T23:59:59.999Z'

                    # Initalise an API object
                    api = KinesisApi(
                        self.api_public_key,
                        self.api_private_key,
                        self.api_url
                    )

                    # Get the price on the day the yield was payed
                    price_info = api.getOHLC(
                        currency_pair,
                        from_date,
                        to_date,
                        '1440'
                    )

                    if price_info:
                        # Calculate the total value of the yield
                        yield_value = D(float(price_info[0].get('low')) * float(deposited_units.number))

                        # Calculate the rate
                        yield_rate = D(float(yield_value) / float(deposited_units.number))

                        # Create a cost object for the yield
                        cost = position.Cost(round(yield_rate, 2), 'GBP', None, None)

                    # Generate the description
                    if rtype == 'Holders_Distribution':
                        yield_name = 'Holders Yield Payment'
                    elif rtype == 'Holders_Yield_Distribution_Adjustment':
                        yield_name = 'Holders Yield Adjustment'
                    elif rtype == 'Velocity_Distribution':
                        yield_name = 'Velocity Yield Payment'

                    desc = f'Kinesis {row["Currency_Code"]} {yield_name}'

                    txn = data.Transaction(
                        meta, date, self.FLAG, None, desc, data.EMPTY_SET, {link}, [
                            data.Posting(source_account, -deposited_units, cost, None, None, None),
                            data.Posting(destination_account, deposited_units, cost, None, None, None)
                        ])

                else:
                    logging.error("Unknown row type: %s; skipping", rtype)
                    continue

                entries.append(txn)

        return entries
