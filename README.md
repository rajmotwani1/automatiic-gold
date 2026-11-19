# Automatic Candle Range & Best Timing Scanner

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy
Upload `app.py`, `requirements.txt`, `README.md`, `START_HERE.txt` and `.gitignore` to a new GitHub repository. Deploy on Streamlit Community Cloud with `app.py` as Main file. No broker token is needed.

## Data
- BTC Spot: Binance public klines.
- BTC Perpetual: Binance USDⓈ-M Futures; Bybit Linear public API fallback.
- Gold: Yahoo Finance XAUUSD=X; GC=F futures fallback is not identical to spot XAUUSD.

## Test rule
BUY: closed bullish candle closes above prior candle high.
SELL: closed bearish candle closes below prior candle low.
Entry: next candle open. SL: signal candle low/high plus user buffer. Target: selected R:R.
If SL and TP both touch in the same candle, SL is assumed first. Positions are closed after 24 bars if neither is hit.
Best time is ranked by IST hour and requires at least 5 trades in that hour.
This is a research/paper-testing tool, not a promise of profitable trades.
