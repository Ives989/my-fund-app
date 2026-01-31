import streamlit as st
import pandas as pd
import efinance as ef
import requests
import re
import json
import time
import plotly.graph_objects as go
from datetime import datetime

# --- 1. 配置与样式优化 ---
st.set_page_config(page_title="智投 Pro", layout="wide", initial_sidebar_state="collapsed")

# 手机端视觉优化 CSS
st.markdown("""
    <style>
    .stMetric { background-color: #f0f2f6; padding: 10px; border-radius: 10px; }
    .main .block-container { padding-top: 1rem; }
    div[data-testid="stExpander"] { border: none; box-shadow: 0px 4px 6px rgba(0,0,0,0.1); }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 持久化存储 ---
DB_FILE = "portfolio.json"

def load_data():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_data(data):
    with open(DB_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)

# --- 3. 数据抓取核心 ---
@st.cache_data(ttl=15)
def fetch_official(code):
    """官方估值接口"""
    try:
        url = f"http://fundgz.1234567.com.cn/js/{code}.js"
        res = requests.get(url, timeout=3)
        data = json.loads(re.match(r"jsonpgz\((.*)\);", res.text).group(1))
        return {"change": float(data['gszzl']), "val": float(data['gsz']), "last": float(data['dwjz']), "time": data['gztime'][-5:]}
    except: return None

@st.cache_data(ttl=3600)
def fetch_shadow(code):
    """影子估值：解析重仓股"""
    try:
        url = f"http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=10"
        df = pd.read_html(url)[0]
        df['代码'] = df['股票代码'].astype(str).str.zfill(6)
        df['权重'] = df['持仓占比'].str.replace('%', '').astype(float)
        quotes = ef.stock.get_quote(df['代码'].tolist())
        merged = pd.merge(df, quotes[['股票代码', '涨跌幅']], left_on='代码', right_on='股票代码')
        # 加权计算
        top10_weight = merged['权重'].sum()
        top10_profit = (merged['权重'] * merged['涨跌幅']).sum() / 100
        hs300 = ef.stock.get_quote(['000300'])['涨跌幅'].values[0]
        return round(top10_profit + (100 - top10_weight) * hs300 / 100, 2)
    except: return 0.0

# --- 4. 手机端主界面 ---
st.title("📈 智投看板 Pro")

# 模式切换
mode = st.tabs(["🚀 官方模式", "🛡️ 影子模式", "⚙️ 持仓管理"])

with mode[2]: # 持仓管理
    with st.expander("➕ 添加/修改基金"):
        c1, c2 = st.columns(2)
        nc = c1.text_input("代码", placeholder="6位")
        nn = c2.text_input("简称")
        ns = st.number_input("持有份额", min_value=0.0)
        if st.button("保存持仓"):
            curr = load_data()
            curr.append({"code": nc, "name": nn, "shares": ns})
            save_data(curr)
            st.rerun()
    if st.button("🗑️ 清空数据"):
        save_data([]); st.rerun()

portfolio = load_data()

# 数据显示逻辑
if not portfolio:
    st.info("手机点击‘持仓管理’添加你的第一支基金")
else:
    results = []
    with st.spinner('同步行情中...'):
        for f in portfolio:
            if "官方" in st.session_state.get('last_tab', '🚀 官方模式'):
                d = fetch_official(f['code'])
                if d:
                    profit = (d['val'] - d['last']) * f['shares']
                    results.append({"基金": f['name'], "涨跌": d['change'], "盈亏": profit, "更新": d['time']})
            else:
                s_change = fetch_shadow(f['code'])
                results.append({"基金": f['name'], "涨跌": s_change, "盈亏": 0.0, "更新": "影子计算"}) # 影子模式仅看涨跌

    if results:
        df = pd.DataFrame(results)
        # 1. 总览指标
        total_p = df['盈亏'].sum()
        st.metric("今日预计总收益", f"¥{total_p:,.2f}", f"{df['涨跌'].mean():+.2f}%")

        # 2. 实时热力图
        fig = go.Figure(go.Bar(x=df['基金'], y=df['涨跌'], 
                               marker_color=['#ef553b' if x >= 0 else '#00cc96' for x in df['涨跌']]))
        fig.update_layout(height=250, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

        # 3. 详细明细 (适配手机滑动)
        st.dataframe(df, use_container_width=True)

    # 自动刷新开关
    if st.toggle("开启自动刷新 (15s)", value=True):
        time.sleep(15)
        st.rerun()
