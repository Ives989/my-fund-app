import os
import sys
import pathlib
import shutil

# --- 核心修复：解决云端只读权限问题 ---
# 1. 强制重定向缓存
os.environ['EF_CACHE_DIR'] = '/tmp/efinance_cache'

# 2. 拦截并空转 mkdir 函数，防止第三方库尝试创建系统目录
def mock_mkdir(*args, **kwargs):
    pass
pathlib.Path.mkdir = mock_mkdir

# --- 导入正式库 ---
import streamlit as st
import pandas as pd
import efinance as ef
import requests
import re
import json
import time
import plotly.graph_objects as go
from datetime import datetime

# --- 配置与样式 ---
st.set_page_config(page_title="智投 Pro 手机版", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; border: 1px solid #eeeeee; padding: 15px; border-radius: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .main .block-container { padding-top: 1rem; }
    div[data-testid="stExpander"] { border: none !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 数据存储 ---
DB_FILE = "portfolio.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return []
    return []

def save_data(data):
    with open(DB_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)

# --- 数据抓取引擎 ---
@st.cache_data(ttl=15)
def fetch_official(code):
    try:
        url = f"http://fundgz.1234567.com.cn/js/{code}.js"
        res = requests.get(url, timeout=5, headers={"Referer": "http://fund.eastmoney.com/"})
        data = json.loads(re.match(r"jsonpgz\((.*)\);", res.text).group(1))
        return {
            "name": data['name'],
            "change": float(data['gszzl']),
            "val": float(data['gsz']),
            "last": float(data['dwjz']),
            "time": data['gztime'][-5:]
        }
    except: return None

@st.cache_data(ttl=3600)
def fetch_shadow(code):
    try:
        url = f"http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=10"
        df = pd.read_html(url)[0]
        df['代码'] = df['股票代码'].astype(str).str.zfill(6)
        df['权重'] = df['持仓占比'].str.replace('%', '').astype(float)
        
        # 获取重仓股行情
        stock_codes = df['代码'].tolist()
        quotes = ef.stock.get_quote(stock_codes)
        merged = pd.merge(df, quotes[['股票代码', '涨跌幅']], left_on='代码', right_on='股票代码')
        
        top10_weight = merged['权重'].sum()
        top10_profit = (merged['权重'] * merged['涨跌幅']).sum() / 100
        
        # 剩余仓位参考沪深300
        hs300 = ef.stock.get_quote(['000300'])['涨跌幅'].values[0]
        remain_profit = ((100 - top10_weight) * hs300) / 100
        
        return round(top10_profit + remain_profit, 2)
    except: return 0.0

# --- 主界面 ---
st.title("📈 智投看板 Pro")

tab_home, tab_manage = st.tabs(["📊 实时行情", "⚙️ 持仓管理"])

with tab_manage:
    with st.expander("➕ 添加基金持仓"):
        c_code = st.text_input("基金代码")
        c_name = st.text_input("简称")
        c_shares = st.number_input("持有份额", min_value=0.0, step=1.0)
        if st.button("确认添加"):
            if c_code and c_name:
                curr = load_data()
                curr.append({"code": c_code, "name": c_name, "shares": c_shares})
                save_data(curr)
                st.success("已保存！")
                time.sleep(1)
                st.rerun()
    
    if st.button("🗑️ 清空所有数据"):
        save_data([])
        st.rerun()

with tab_home:
    portfolio = load_data()
    if not portfolio:
        st.info("请先在‘持仓管理’中添加基金代码。")
    else:
        use_shadow = st.toggle("🛡️ 开启影子估值 (防封模式)", value=False)
        
        results = []
        with st.spinner('正在同步数据...'):
            for f in portfolio:
                if not use_shadow:
                    d = fetch_official(f['code'])
                    if d:
                        profit = (d['val'] - d['last']) * f['shares']
                        results.append({"基金": f['name'], "涨跌%": d['change'], "预计盈亏": profit, "时间": d['time']})
                else:
                    s_change = fetch_shadow(f['code'])
                    results.append({"基金": f['name'], "涨跌%": s_change, "预计盈亏": 0.0, "时间": "影子计算"})

        if results:
            df_res = pd.DataFrame(results)
            
            # 总览指标
            total_p = df_res['预计盈亏'].sum()
            avg_c = df_res['涨跌%'].mean()
            col1, col2 = st.columns(2)
            col1.metric("今日收益", f"¥{total_p:,.2f}", f"{avg_c:+.2f}%")
            col2.metric("刷新频率", "15秒/次", "Live")

            # 柱状图
            fig = go.Figure(go.Bar(
                x=df_res['基金'], y=df_res['涨跌%'],
                marker_color=['#ef553b' if x >= 0 else '#00cc96' for x in df_res['涨跌%']]
            ))
            fig.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

            # 详细列表
            st.dataframe(df_res, use_container_width=True)

            if not use_shadow and st.toggle("开启实时盯盘", value=True):
                time.sleep(15)
                st.rerun()
