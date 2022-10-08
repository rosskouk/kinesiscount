# KinesisCount

KinesisCount is an importer for Beancount that processes Account Balance CSV files from Kinesis.Money.  The importer will parse the CSV and extract both trades and yield payments.  The Kinesis API is used to add the days price to yield payments as a cost basis and trades are automatically split into different accounts depending on which currency was used to keep cost bases seperate to ease the calculation of capital gains.

## Installation

Install setuptools in your environment and install the module with pip

## Configuration

In order to use the importer you must create a configuration file with the following content

```python
import sys
from os import path
sys.path.insert(0, path.join(path.dirname(__file__)))

from importers.kinesiscount import kinesis_cointracker_csv
from beancount.ingest import extract

CONFIG = [kinesis_cointracker_csv.Importer("Assets:Top:Level:Kinesis:Exchange:Account",
                                           "Expenses:Top:Level:Kinesis:Expenses:Account",
                                           "Uncategorised-Transactions",
                                           "Public Kinesis API Key",
                                           "Private API Key",
                                           "https://URL to Kinesis API"
                                           )]

extract.HEADER = ';; -*- mode: org; mode: beancount; coding: utf-8; -*-\n'
```

## Using The Importer

1. Download the Account Balance Statement from your Kinesis.Money account.
2. Test that the importer can identify the file
   ```bash
   bean-identify config-file.py /Path/To/Downloaded/CSV
   ```
3. Extract the transactions
   ```bash
    bean-extract -e main_ledger_file.bean config-file.py /Path/To/Downloaded/CSV
   ```
4. Archive the document
   ```bash
   bean-file config-file.py /Path/To/Downloaded/CSV -o folder_to_save_in
   ```

## References

https://beancount.github.io/docs/importing_external_data.html#organizing-your-files
