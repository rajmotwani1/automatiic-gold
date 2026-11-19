
import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import yfinance as yf

st.set_page_config(page_title="Candle Range & Timing Scanner", page_icon="⏱️", layout="wide")
IST = ZoneInfo("Asia/Kolkata")
SPOT = "https://data-api.binance.vision"
FUT = "https://fapi.binance.com"
BYBIT = "https://api.bybit.com"
TF_MS = {"1m":60000,"3m":180000,"5m":300000,"15m":900000,"30m":1800000,"1h":3600000,"2h":7200000,"3h":10800000,"4h":14400000}
BYBIT_TF = {"1m":"1","3m":"3","5m":"5","15m":"15","30m":"30","1h":"60","2h":"120","4h":"240"}

def clean(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["time","open","high","low","close","volume"])
    x=df.copy()
    x["time"]=pd.to_datetime(x["time"],utc=True,errors="coerce")
    for c in ["open","high","low","close","volume"]:
        x[c]=pd.to_numeric(x[c],errors="coerce")
    return x.dropna(subset=["time","open","high","low","close"])[["time","open","high","low","close","volume"]].sort_values("time").drop_duplicates("time").reset_index(drop=True)

@st.cache_data(ttl=120,show_spinner=False)
def binance_data(market,tf,days):
    base,path=(SPOT,"/api/v3/klines") if market=="BTC Spot" else (FUT,"/fapi/v1/klines")
    end=int(datetime.now(timezone.utc).timestamp()*1000); cursor=end-days*86400000; rows=[]
    while cursor<end:
        r=requests.get(base+path,params={"symbol":"BTCUSDT","interval":tf,"startTime":cursor,"endTime":end,"limit":1000},timeout=20)
        r.raise_for_status(); batch=r.json()
        if not isinstance(batch,list): raise RuntimeError(str(batch)[:250])
        if not batch: break
        rows.extend(batch); nxt=int(batch[-1][0])+TF_MS[tf]
        if nxt<=cursor: break
        cursor=nxt
        if len(batch)<1000: break
    if not rows: return pd.DataFrame()
    cols=["time","open","high","low","close","volume","close_time","qv","trades","tb","tq","ignore"]
    x=pd.DataFrame(rows,columns=cols); x["time"]=pd.to_datetime(x["time"],unit="ms",utc=True)
    return clean(x)

@st.cache_data(ttl=120,show_spinner=False)
def bybit_data(tf,days):
    if tf=="3h":
        h=bybit_data("1h",days)
        if h.empty:return h
        return clean(h.set_index("time").resample("3h",origin="start_day").agg(open=("open","first"),high=("high","max"),low=("low","min"),close=("close","last"),volume=("volume","sum")).dropna().reset_index())
    end=int(datetime.now(timezone.utc).timestamp()*1000); start=end-days*86400000; cursor=end; rows=[]
    while cursor>start:
        p={"category":"linear","symbol":"BTCUSDT","interval":BYBIT_TF[tf],"start":start,"end":cursor,"limit":1000}
        r=requests.get(BYBIT+"/v5/market/kline",params=p,timeout=20);r.raise_for_status();j=r.json()
        if j.get("retCode")!=0:raise RuntimeError(j.get("retMsg","Bybit error"))
        batch=j.get("result",{}).get("list",[])
        if not batch:break
        rows.extend(batch); oldest=min(int(z[0]) for z in batch)
        if oldest<=start or len(batch)<1000:break
        cursor=oldest-1
    if not rows:return pd.DataFrame()
    x=pd.DataFrame(rows,columns=["time","open","high","low","close","volume","turnover"])
    x["time"]=pd.to_datetime(pd.to_numeric(x["time"]),unit="ms",utc=True)
    return clean(x)

@st.cache_data(ttl=300,show_spinner=False)
def gold_data(tf,days):
    interval={"1m":"1m","3m":"5m","5m":"5m","15m":"15m","30m":"30m","1h":"60m","2h":"60m","3h":"60m","4h":"60m"}[tf]
    period="7d" if interval=="1m" else ("60d" if interval in ["5m","15m","30m"] else "730d")
    errors=[]
    for ticker in ["XAUUSD=X","GC=F"]:
        try:
            x=yf.download(ticker,period=period,interval=interval,auto_adjust=False,progress=False,threads=False)
            if x is None or x.empty:continue
            if isinstance(x.columns,pd.MultiIndex):x.columns=x.columns.get_level_values(0)
            x=x.reset_index();tc="Datetime" if "Datetime" in x.columns else "Date"
            x=x.rename(columns={tc:"time","Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
            x=clean(x);x=x[x.time>=pd.Timestamp.now(tz="UTC")-pd.Timedelta(days=days)]
            if tf in ["2h","3h","4h"] and not x.empty:
                x=clean(x.set_index("time").resample(tf,origin="start_day").agg(open=("open","first"),high=("high","max"),low=("low","min"),close=("close","last"),volume=("volume","sum")).dropna().reset_index())
            if not x.empty:
                x.attrs["source"]="Yahoo Finance "+ticker
                return x
        except Exception as e:errors.append(f"{ticker}: {e}")
    raise RuntimeError("Gold feed unavailable: "+" | ".join(errors))

def download(market,tf,days):
    if market=="XAUUSD":return gold_data(tf,days)
    if market=="BTC Spot":
        x=binance_data(market,tf,days);x.attrs["source"]="Binance Spot";return x
    errors=[]
    try:
        x=binance_data(market,tf,days)
        if not x.empty:x.attrs["source"]="Binance USDⓈ-M Futures";return x
    except Exception as e:errors.append("Binance Futures: "+str(e))
    try:
        x=bybit_data(tf,days)
        if not x.empty:x.attrs["source"]="Bybit Linear Perpetual fallback";return x
    except Exception as e:errors.append("Bybit fallback: "+str(e))
    raise RuntimeError("Perpetual data failed. "+" | ".join(errors))

def analyse_candles(x):
    x=x.copy();x["range"]=x.high-x.low;x["range_pct"]=x["range"]/x.close*100
    x["type"]=np.where(x.close>x.open,"Bullish",np.where(x.close<x.open,"Bearish","Doji"))
    return x

def backtest(x,rr,buffer,hold_bars=24):
    trades=[]
    for i in range(1,len(x)-1):
        s=x.iloc[i];prev=x.iloc[i-1];entrybar=x.iloc[i+1]
        side="BUY" if s.close>prev.high and s.close>s.open else ("SELL" if s.close<prev.low and s.close<s.open else None)
        if not side:continue
        entry=float(entrybar.open)
        sl=float(s.low-buffer) if side=="BUY" else float(s.high+buffer)
        risk=entry-sl if side=="BUY" else sl-entry
        if risk<=0:continue
        target=entry+rr*risk if side=="BUY" else entry-rr*risk
        last=min(len(x)-1,i+1+hold_bars);exitp=None;outcome="TIME EXIT";exittime=x.iloc[last].time
        for j in range(i+1,last+1):
            b=x.iloc[j]
            hit_sl=(b.low<=sl) if side=="BUY" else (b.high>=sl)
            hit_tp=(b.high>=target) if side=="BUY" else (b.low<=target)
            if hit_sl:exitp=sl;outcome="LOSS";exittime=b.time;break
            if hit_tp:exitp=target;outcome="WIN";exittime=b.time;break
        if exitp is None:exitp=float(x.iloc[last].close)
        pnl=exitp-entry if side=="BUY" else entry-exitp
        ist=s.time.tz_convert(IST)
        trades.append({"Signal Time (IST)":ist.strftime("%Y-%m-%d %H:%M"),"Hour (IST)":ist.hour,
                       "Weekday":ist.strftime("%a"),"Side":side,"Entry":entry,"SL":sl,"Target":target,
                       "Exit":exitp,"Outcome":outcome,"P&L":pnl,"R":pnl/risk,
                       "Signal High":float(s.high),"Signal Low":float(s.low),"Candle Range":float(s.high-s.low)})
    return pd.DataFrame(trades)

def rank_hours(t):
    if t.empty:return pd.DataFrame()
    rows=[]
    for hour,g in t.groupby("Hour (IST)"):
        wins=(g.Outcome=="WIN").sum();gross_win=g.loc[g.R>0,"R"].sum();gross_loss=abs(g.loc[g.R<0,"R"].sum())
        rows.append({"Hour IST":f"{int(hour):02d}:00","Trades":len(g),"Wins":int(wins),
                     "Win Rate %":round(wins/len(g)*100,1),"Net R":round(g.R.sum(),2),
                     "Avg R":round(g.R.mean(),2),"Profit Factor":round(gross_win/gross_loss,2) if gross_loss else np.inf,
                     "Timing Score":g.R.sum()/np.sqrt(len(g)) if len(g)>=5 else np.nan})
    return pd.DataFrame(rows).sort_values(["Timing Score","Trades"],ascending=False)

st.title("⏱️ Automatic Candle Range & Best Timing Scanner")
st.caption("BTC Spot • BTC Perpetual • XAUUSD | Automatic candle High/Low | Best historical time slots")
with st.sidebar:
    st.header("Settings")
    market=st.selectbox("Market",["BTC Spot","BTC Perpetual","XAUUSD"])
    tf=st.selectbox("Timeframe",list(TF_MS),index=2)
    days=st.selectbox("Lookback days",[7,14,30,60],index=2)
    rr=st.selectbox("Risk : Reward",[1.0,1.5,2.0,3.0],index=2)
    buffer=st.number_input("SL buffer (price units)",min_value=0.0,value=0.0,step=0.1)
    bars=st.slider("Chart candles",30,250,80,10)
    go=st.button("Download Data & Analyse",type="primary",use_container_width=True)

st.info("Baseline rule: BUY when a completed bullish candle closes above the previous candle high; SELL when a completed bearish candle closes below the previous candle low. Entry is next candle open. SL uses signal candle low/high plus buffer; target uses selected R:R.")
if go:
    try:
        with st.spinner("Downloading market candles and analysing..."):
            data=download(market,tf,days)
        if data.empty or len(data)<10:st.error("Not enough candle data returned.");st.stop()
        data=analyse_candles(data);trades=backtest(data,rr,buffer)
        st.session_state["cr_data"]=data;st.session_state["cr_trades"]=trades
        st.session_state["cr_market"]=market;st.session_state["cr_tf"]=tf
        st.session_state["cr_source"]=data.attrs.get("source","Market data provider")
    except Exception as e:st.error(f"Download / analysis error: {e}");st.stop()

if "cr_data" in st.session_state:
    data=st.session_state["cr_data"];trades=st.session_state["cr_trades"]
    st.caption(f"Source: {st.session_state['cr_source']} | Last candle: {data.time.iloc[-1].tz_convert(IST).strftime('%d-%b-%Y %I:%M %p')} IST")
    a,b,c,d=st.columns(4)
    a.metric("Candles",f"{len(data):,}");b.metric("Avg candle range",f"{data['range'].mean():.4f}")
    c.metric("Largest range",f"{data['range'].max():.4f}");d.metric("Breakout trades",len(trades))
    st.subheader("Candlestick chart with automatic High / Low")
    v=data.tail(bars)
    fig=go.Figure(go.Candlestick(x=v.time,open=v.open,high=v.high,low=v.low,close=v.close,name="Price"))
    for _,r in v.iterrows():
        fig.add_shape(type="line",x0=r.time,x1=r.time,y0=r.low,y1=r.high,line=dict(color="rgba(120,140,160,.35)",width=1))
    fig.update_layout(template="plotly_dark",height=600,xaxis_rangeslider_visible=False,margin=dict(l=5,r=5,t=25,b=5))
    st.plotly_chart(fig,use_container_width=True)
    st.subheader("Candle High / Low / Range")
    table=data.tail(300).copy();table["Time IST"]=table.time.dt.tz_convert(IST).dt.strftime("%d-%b %H:%M")
    st.dataframe(table[["Time IST","open","high","low","close","range","range_pct","type"]].rename(
        columns={"open":"Open","high":"High","low":"Low","close":"Close","range":"Range","range_pct":"Range %","type":"Candle"}),
        use_container_width=True,hide_index=True)
    st.subheader("Best trading time slots (IST)")
    if trades.empty:
        st.warning("No qualifying breakout trades found for this period/timeframe.")
    else:
        ranking=rank_hours(trades);eligible=ranking.dropna(subset=["Timing Score"]).head(5)
        if eligible.empty:st.warning("Kisi hour mein 5 trades ka minimum sample nahi mila; more history ya another timeframe try karo.")
        else:st.success("Top historical time slots: "+", ".join(eligible["Hour IST"].tolist()))
        st.dataframe(ranking,use_container_width=True,hide_index=True)
        wins=int((trades.Outcome=="WIN").sum())
        p,q,r,s=st.columns(4);p.metric("Wins",wins);q.metric("Stop exits",int((trades.Outcome=="LOSS").sum()))
        r.metric("Win rate",f"{wins/len(trades)*100:.1f}%");s.metric("Net R",f"{trades.R.sum():.2f}R")
        st.subheader("Backtest trades")
        st.dataframe(trades,use_container_width=True,hide_index=True)
        st.download_button("Download trades CSV",trades.to_csv(index=False).encode(),f"{market}_{tf}_trades.csv","text/csv")
        st.download_button("Download timing ranking CSV",ranking.to_csv(index=False).encode(),f"{market}_{tf}_timing.csv","text/csv")

st.caption("BTC Spot uses Binance public candles. BTC Perpetual uses Binance Futures with Bybit Linear fallback. Gold uses Yahoo Finance XAUUSD=X; GC=F is a futures fallback and is not identical to spot XAUUSD. Same-candle SL/TP hits are counted as SL first. Time ranking requires at least five trades per hour. Historical performance is not a guarantee.")
