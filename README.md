# Automatic Candle Range & Best Timing Scanner

## What it does
- Automatic mode scans **both 5-minute and 15-minute candles** for BTC Spot, BTC Perpetual and XAUUSD.
- Automatically marks each completed candle's High and Low on the chart and lists OHLC/range values.
- Refreshes automatically every 60 seconds (toggle in the sidebar); unfinished candles are excluded from signals and backtests.
- Finds the strongest recurring candle start-times (HH:MM IST) from the selected lookback and ranks them by profitable-trade accuracy, net R, average R and profit factor.
- Shows BUY/SELL breakout trades, entry, SL, target, exit and CSV exports separately for 5m and 15m.
- Manual timeframe mode remains available for the original timeframe list.

## Existing trading rules and settings retained
BUY: completed bullish candle closes above previous candle high.
SELL: completed bearish candle closes below previous candle low.
Entry: next candle open. SL: signal candle low/high plus editable buffer. Target: selected Risk:Reward. If SL and target both touch in one candle, SL is assumed first. Trades are force-closed after 24 bars if neither is hit.

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy
Upload `app.py`, `requirements.txt`, `README.md`, `START_HERE.txt` and `.gitignore` to a GitHub repository. Deploy on Streamlit Community Cloud with `app.py` as Main file. No broker token is needed.

## Data feeds
- BTC Spot: Binance public klines.
- BTC Perpetual: Binance USDⓈ-M Futures; Bybit Linear public API fallback.
- Gold: Yahoo Finance XAUUSD=X; GC=F futures fallback is not identical to spot XAUUSD.

## Important
Accuracy is historical and sample-size dependent, not a guarantee of future results. A candle time is only ranked after the selected minimum number of historical trades. This is a research/paper-testing tool; it does not place orders.
