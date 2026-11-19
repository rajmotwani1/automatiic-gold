
import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import yfinance as yf
from streamlit_autorefresh import st_autorefresh

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

@st.cache_data(ttl=45,show_spinner=False)
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

@st.cache_data(ttl=45,show_spinner=False)
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

@st.cache_data(ttl=60,show_spinner=False)
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

def analyse_candles(x,tf):
    x=x.copy()
    # Never generate a signal from an unfinished candle.
    cutoff=pd.Timestamp.now(tz="UTC")
    x=x[x.time+pd.to_timedelta(TF_MS[tf],unit="ms")<=cutoff].copy()
    x["range"]=x.high-x.low;x["range_pct"]=x["range"]/x.close*100
    prev_close=x.close.shift(1)
    tr=pd.concat([(x.high-x.low),(x.high-prev_close).abs(),(x.low-prev_close).abs()],axis=1).max(axis=1)
    x["atr"]=tr.rolling(14,min_periods=1).mean()
    x["type"]=np.where(x.close>x.open,"Bullish",np.where(x.close<x.open,"Bearish","Doji"))
    return x

def calculate_trade_levels(side,entry,signal_high,signal_low,signal_range,atr,sl_method,sl_value,target_method,target_value,rr_value,buffer):
    """Build editable SL/target levels from the selected user methods."""
    if sl_method=="Fixed Points":
        risk=float(sl_value)
        sl=entry-risk if side=="BUY" else entry+risk
    elif sl_method=="Percentage":
        risk=entry*float(sl_value)/100.0
        sl=entry-risk if side=="BUY" else entry+risk
    elif sl_method=="Risk:Reward":
        # In this mode SL value is the user-defined risk distance; RR controls the target when selected.
        risk=float(sl_value)
        sl=entry-risk if side=="BUY" else entry+risk
    elif sl_method=="ATR Based":
        risk=max(float(atr),0.0)*float(sl_value)
        sl=entry-risk if side=="BUY" else entry+risk
    else:  # Signal Candle High/Low
        sl=float(signal_low)-float(buffer) if side=="BUY" else float(signal_high)+float(buffer)
        risk=entry-sl if side=="BUY" else sl-entry
    if not np.isfinite(risk) or risk<=0:
        return None,None,None
    if target_method=="Fixed Points":
        reward=float(target_value)
    elif target_method=="Percentage":
        reward=entry*float(target_value)/100.0
    elif target_method=="ATR Based":
        reward=max(float(atr),0.0)*float(target_value)
    elif target_method=="Signal Candle High/Low":
        reward=max(float(signal_range),0.0)*float(target_value)
    else:  # Risk:Reward
        reward=risk*float(rr_value)
    if not np.isfinite(reward) or reward<=0:
        return None,None,None
    target=entry+reward if side=="BUY" else entry-reward
    return float(sl),float(target),float(risk)

def backtest(x,sl_method,sl_value,target_method,target_value,rr_value,buffer,hold_bars=24):
    trades=[]
    for i in range(1,len(x)-1):
        s=x.iloc[i];prev=x.iloc[i-1];entrybar=x.iloc[i+1]
        side="BUY" if s.close>prev.high and s.close>s.open else ("SELL" if s.close<prev.low and s.close<s.open else None)
        if not side:continue
        entry=float(entrybar.open)
        sl,target,risk=calculate_trade_levels(side,entry,float(s.high),float(s.low),float(s.high-s.low),float(s.atr),sl_method,sl_value,target_method,target_value,rr_value,buffer)
        if sl is None or target is None:continue
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
                       "Candle Slot (IST)":ist.strftime("%H:%M"),"Weekday":ist.strftime("%a"),"Side":side,"Entry":entry,"SL":sl,"Target":target,
                       "SL Method":sl_method,"SL Setting":sl_value,"Target Method":target_method,"Target Setting":target_value,"RR Multiplier":rr_value,
                       "Exit":exitp,"Outcome":outcome,"P&L":pnl,"R":pnl/risk,
                       "Signal High":float(s.high),"Signal Low":float(s.low),"Candle Range":float(s.high-s.low)})
    return pd.DataFrame(trades)

def rank_candle_slots(t,min_trades=5):
    """Rank recurring candle start-times (HH:MM IST) by profitable-trade accuracy and R."""
    if t.empty:return pd.DataFrame()
    rows=[]
    for slot,g in t.groupby("Candle Slot (IST)"):
        wins=int((g["P&L"]>0).sum());losses=int((g["P&L"]<=0).sum())
        gross_win=float(g.loc[g.R>0,"R"].sum());gross_loss=abs(float(g.loc[g.R<0,"R"].sum()))
        side_stats={side:float((z["P&L"]>0).mean()) for side,z in g.groupby("Side")}
        best_side=max(side_stats,key=side_stats.get) if side_stats else "—"
        rows.append({"Candle Time (IST)":slot,"Best Direction":best_side,"Trades":len(g),"Winning Trades":wins,"Losing Trades":losses,
                     "Accuracy %":round(wins/len(g)*100,1),"Net R":round(float(g.R.sum()),2),
                     "Average R":round(float(g.R.mean()),2),
                     "Profit Factor":round(gross_win/gross_loss,2) if gross_loss else np.inf,
                     "Timing Score":round(float(g.R.sum()/np.sqrt(len(g))),3) if len(g)>=min_trades else np.nan})
    return pd.DataFrame(rows).sort_values(["Accuracy %","Timing Score","Trades"],ascending=False,na_position="last").reset_index(drop=True)

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
st.caption("BTC Spot • BTC Perpetual • XAUUSD | Auto 5m + 15m candle marking | Best recurring candle-time finder")
with st.sidebar:
    st.header("Settings")
    market=st.selectbox("Market",["BTC Spot","BTC Perpetual","XAUUSD"])
    mode=st.selectbox("Scan mode",["Automatic 5m + 15m","Manual timeframe"],index=0)
    if mode=="Manual timeframe":
        tf=st.selectbox("Timeframe",list(TF_MS),index=2)
        scan_tfs=[tf]
    else:
        scan_tfs=["5m","15m"]
        st.caption("5-minute aur 15-minute dono charts automatically scan honge.")
    days=st.selectbox("Lookback days",[7,14,30,60],index=2)
    st.subheader("Stop Loss Settings")
    sl_method=st.selectbox("Stop Loss method",["Signal Candle High/Low","Fixed Points","Percentage","Risk:Reward","ATR Based"],index=0)
    sl_value=st.number_input("SL value (points / % / ATR multiplier)",min_value=0.01,value=20.0,step=0.5)
    buffer=st.number_input("Signal candle SL buffer (price units)",min_value=0.0,value=0.0,step=0.1)
    st.subheader("Target Settings")
    target_method=st.selectbox("Target method",["Risk:Reward","Fixed Points","Percentage","Signal Candle High/Low","ATR Based"],index=0)
    target_value=st.number_input("Target value (points / % / candle-range or ATR multiplier)",min_value=0.01,value=40.0,step=0.5)
    rr=st.selectbox("Risk : Reward multiplier",[1.0,1.5,2.0,3.0,4.0,5.0],index=2)
    st.caption("Signal Candle SL uses signal candle Low for BUY / High for SELL. Risk:Reward target = SL risk × RR. Other target methods use the entered target value.")
    bars=st.slider("Chart candles",30,250,80,10)
    min_trades=st.selectbox("Minimum trades to rank a candle time",[5,10,20],index=0)
    auto_update=st.checkbox("Auto update every 60 seconds",value=True)
    refresh_count=st_autorefresh(interval=60_000,key="candle_scanner_refresh") if auto_update else 0
    run_scan=st.button("Download Data & Analyse",type="primary",use_container_width=True)

st.info("Automatic mode marks every completed 5-minute and 15-minute candle. BUY: a completed bullish candle closes above the previous candle high. SELL: a completed bearish candle closes below the previous candle low. Entry is next candle open. SL and Target follow the editable methods selected in the sidebar. Incomplete live candles are excluded.")
current_settings={"sl_method":sl_method,"sl_value":sl_value,"target_method":target_method,"target_value":target_value,"rr":rr,"buffer":buffer}
settings_changed=st.session_state.get("cr_settings")!=current_settings
should_scan=run_scan or settings_changed or (auto_update and (refresh_count>0 or "cr_results" not in st.session_state))
if should_scan:
    results={};errors=[]
    progress=st.progress(0);status=st.empty()
    try:
        for idx,scan_tf in enumerate(scan_tfs,1):
            status.write(f"Downloading and analysing {market} {scan_tf}...")
            try:
                with st.spinner(f"Processing {market} {scan_tf} candles..."):
                    raw=download(market,scan_tf,days)
                if raw.empty:raise RuntimeError("No candle data returned")
                data=analyse_candles(raw,scan_tf)
                if len(data)<10:raise RuntimeError("Not enough completed candle data")
                trades=backtest(data,sl_method,sl_value,target_method,target_value,rr,buffer)
                ranking=rank_candle_slots(trades,min_trades)
                results[scan_tf]={"data":data,"trades":trades,"ranking":ranking,
                                  "source":raw.attrs.get("source","Market data provider")}
            except Exception as e:
                errors.append(f"{scan_tf}: {e}")
            progress.progress(idx/max(len(scan_tfs),1))
        st.session_state["cr_results"]=results
        st.session_state["cr_errors"]=errors
        st.session_state["cr_market"]=market
        st.session_state["cr_tfs"]=scan_tfs
        st.session_state["cr_days"]=days
        st.session_state["cr_rr"]=rr
        st.session_state["cr_buffer"]=buffer
        st.session_state["cr_settings"]=current_settings
    finally:
        status.empty()
        progress.empty()

if "cr_results" in st.session_state:
    results=st.session_state["cr_results"]
    st.caption(f"Market: {st.session_state['cr_market']} | Lookback: {st.session_state['cr_days']} days | Auto refresh: {'ON' if auto_update else 'OFF'} | Last refresh: {datetime.now(IST).strftime('%d-%b-%Y %I:%M:%S %p')} IST")
    if st.session_state.get("cr_errors"):
        for err in st.session_state["cr_errors"]:st.warning(f"Data issue — {err}")
    if not results:
        st.error("No timeframe data was successfully loaded. Check the data feed and try again.")
    for scan_tf in st.session_state.get("cr_tfs",[]):
        if scan_tf not in results:continue
        pack=results[scan_tf];data=pack["data"];trades=pack["trades"];ranking=pack["ranking"]
        st.divider()
        st.header(f"{scan_tf} Automatic Candle Scanner")
        st.caption(f"Source: {pack['source']} | Completed candles: {len(data):,} | Last completed candle: {data.time.iloc[-1].tz_convert(IST).strftime('%d-%b-%Y %I:%M %p')} IST")
        a,b,c,d=st.columns(4)
        a.metric("Candles marked",f"{len(data):,}");b.metric("Average range",f"{data['range'].mean():.4f}")
        c.metric("Largest range",f"{data['range'].max():.4f}");d.metric("Breakout trades",len(trades))
        st.subheader(f"{scan_tf} chart — automatic High / Low marking")
        v=data.tail(bars)
        fig=go.Figure(go.Candlestick(x=v.time,open=v.open,high=v.high,low=v.low,close=v.close,name="Price"))
        # Draw the high and low of every visible candle as short horizontal range markers.
        for _,r0 in v.iterrows():
            end_time=r0.time+pd.Timedelta(milliseconds=TF_MS[scan_tf])
            fig.add_shape(type="line",x0=r0.time,x1=end_time,y0=r0.high,y1=r0.high,line=dict(color="rgba(40,190,120,.75)",width=1))
            fig.add_shape(type="line",x0=r0.time,x1=end_time,y0=r0.low,y1=r0.low,line=dict(color="rgba(230,90,90,.75)",width=1))
        fig.update_layout(template="plotly_dark",height=560,xaxis_rangeslider_visible=False,margin=dict(l=5,r=5,t=25,b=5))
        st.plotly_chart(fig,use_container_width=True)
        st.subheader("Automatically marked candle High / Low / Range")
        table=data.tail(300).copy();table["Time IST"]=table.time.dt.tz_convert(IST).dt.strftime("%d-%b %H:%M")
        st.dataframe(table[["Time IST","open","high","low","close","range","range_pct","type"]].rename(
            columns={"open":"Open","high":"High","low":"Low","close":"Close","range":"Range","range_pct":"Range %","type":"Candle"}),
            use_container_width=True,hide_index=True)
        st.subheader(f"Best {scan_tf} candle times for trading (IST)")
        if trades.empty:
            st.warning("No qualifying breakout trades found for this timeframe and lookback.")
        else:
            eligible=ranking.dropna(subset=["Timing Score"]).head(10)
            if eligible.empty:
                st.warning(f"No candle time has {min_trades} completed trades yet. Increase lookback or lower the minimum sample setting.")
            else:
                best=eligible.iloc[0]
                st.success(f"Best historical {scan_tf} candle time: {best['Candle Time (IST)']} IST | Accuracy {best['Accuracy %']}% | {int(best['Trades'])} trades")
            st.dataframe(ranking,use_container_width=True,hide_index=True)
            wins=int((trades["P&L"]>0).sum());losses=int((trades["P&L"]<=0).sum())
            p,q,r,s=st.columns(4);p.metric("Profitable trades",wins);q.metric("Losing trades",losses)
            r.metric("Profit accuracy",f"{wins/len(trades)*100:.1f}%");s.metric("Net R",f"{trades.R.sum():.2f}R")
            st.subheader("BUY / SELL breakout trade signals and backtest")
            st.dataframe(trades,use_container_width=True,hide_index=True)
            st.download_button(f"Download {scan_tf} trades CSV",trades.to_csv(index=False).encode(),f"{st.session_state['cr_market']}_{scan_tf}_trades.csv","text/csv",key=f"trades_{scan_tf}")
            st.download_button(f"Download {scan_tf} candle-time ranking CSV",ranking.to_csv(index=False).encode(),f"{st.session_state['cr_market']}_{scan_tf}_timing.csv","text/csv",key=f"ranking_{scan_tf}")

st.caption("BTC Spot uses Binance public candles. BTC Perpetual uses Binance Futures with Bybit Linear fallback. Gold uses Yahoo Finance XAUUSD=X; GC=F is a futures fallback and is not identical to spot XAUUSD. Ranking is by recurring candle start-time (HH:MM IST), based on profitable trades and R-multiple; it is historical analysis, not a guarantee of future accuracy. Same-candle SL/TP hits are counted as SL first. No orders are placed.")
