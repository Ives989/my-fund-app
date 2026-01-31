import os
import sys
import pathlib
import shutil

# --- 1. 核心修复：权限拦截 (解决之前的 PermissionError) ---
os.environ['EF_CACHE_DIR'] = '/tmp/efinance_cache'
def mock_mkdir(*args, **kwargs): pass
pathlib.Path.mkdir = mock_mkdir

# --- 2. 导入依赖 ---
import streamlit as st
import pandas as pd
import efinance as ef
import requests
import re
import json
import time
import plotly.graph_objects as go
from datetime import datetime

# --- 3. 页面配置 ---
st.set_page_config(page_title="智投分时看板", layout="wide", initial_sidebar_state="collapsed")

# --- 4. 初始化“分时记忆” ---
# session_state 用于在页面刷新时保留之前抓取到的数据点
if 'history' not in st.session_state:
    st.session_state.history = pd.DataFrame(columns=['time', 'profit'])

DB_FILE = "portfolio.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return []
    return []

def save_data(data):
    with open(DB_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)

# --- 5. 数据抓取引擎 ---
@st.cache_data(ttl=15)
def fetch_official(code):
    try:
        url = f"http://fundgz.1234567.com.cn/js/{code}.js"
        res = requests.get(url, timeout=5, headers={"Referer": "http://fund.eastmoney.com/"})
        data = json.loads(re.match(r"jsonpgz\((.*)\);", res.text).group(1))
        return {"change": float(data['gszzl']), "val": float(data['gsz']), "last": float(data['dwjz'])}
    except: return None

@st.cache_data(ttl=3600)
def fetch_shadow_v2(code):
    try:
        url = f"http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=10"
        df = pd.read_html(url)[0]
        df['代码'] = df['股票代码'].astype(str).str.zfill(6)
        df['权重'] = df['持仓占比'].str.replace('%', '').astype(float)
        quotes = ef.stock.get_quote(df['代码'].tolist())
        merged = pd.merge(df, quotes[['股票代码', '涨跌幅']], left_on='代码', right_on='股票代码')
        top10_weight, top10_profit = merged['权重'].sum(), (merged['权重'] * merged['涨跌幅']).sum() / 100
        market_data = ef.stock.get_quote(['000300', '399006'])
        hs300, cyb = market_data['涨跌幅'].values[0], market_data['涨跌幅'].values[1]
        is_growth = merged['股票名称'].str.contains('宁德|阳光|药明|隆基|比亚迪|迈瑞|东方财富').any()
        anchor = cyb if is_growth else hs300
        return round((top10_profit + (100 - top10_weight) * anchor / 100) * 0.95, 2)
    except: return 0.0

# --- 6. 主界面渲染 ---
st.title("📈 收益实时分时走势")

tab_home, tab_manage = st.tabs(["📊 走势看板", "⚙️ 持仓管理"])

with tab_manage:
    with st.expander("➕ 添加持仓"):
        c_code = st.text_input("代码")
        c_name = st.text_input("简称")
        c_shares = st.number_input("份额", min_value=0.0, step=100.0)
        if st.button("保存"):
            curr = load_data(); curr.append({"code": c_code, "name": c_name, "shares": c_shares})
            save_data(curr); st.session_state.history = pd.DataFrame(columns=['time', 'profit']); st.rerun()
    if st.button("🗑️ 清空历史线图"):
        st.session_state.history = pd.DataFrame(columns=['time', 'profit']); st.rerun()

with tab_home:
    portfolio = load_data()
    if not portfolio:
        st.warning("请先在持仓管理添加数据")
    else:
        mode = st.radio("模式选择", ["官方模式", "影子拟合 (养基宝逻辑)"], horizontal=True)
        
        # 计算实时总盈亏
        total_p = 0
        now_time = datetime.now().strftime("%H:%M:%S")
        for f in portfolio:
            if "官方" in mode:
                d = fetch_official(f['code'])
                if d: total_p += (d['val'] - d['last']) * f['shares']
            else:
                total_p += (fetch_shadow_v2(f['code']) / 100) * (f['shares'] * 1.0) # 此处假设单价1元简化计算

        # 将新产生的点加入历史记录
        new_row = pd.DataFrame({'time': [now_time], 'profit': [total_p]})
        st.session_state.history = pd.concat([st.session_state.history, new_row], ignore_index=True)
        
        # --- 绘制分时线图 (模仿养基宝) ---
        fig = go.Figure()
        
        # 添加分时线
        fig.add_trace(go.Scatter(
            x=st.session_state.history['time'], 
            y=st.session_state.history['profit'],
            mode='lines',
            line=dict(color='#4c78ff', width=2),
            fill='tozeroy',  # 下方填充，更像养基宝
            fillcolor='rgba(76, 120, 255, 0.1)',
            name="实时盈亏"
        ))

        # 优化图表样式
        fig.update_layout(
            plot_bgcolor='white',
            height=350,
            margin=dict(l=10, r=10, t=30, b=10),
            xaxis=dict(showgrid=True, gridcolor='#f0f0f0', tickangle=0),
            yaxis=dict(showgrid=True, gridcolor='#f0f0f0', zeroline=True, zerolinecolor='#cccccc'),
            hovermode="x unified"
        )
        
        # 在顶部显示实时金额
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        
        c1, c2 = st.columns(2)
        c1.metric("当前总预计盈亏", f"¥{total_p:,.2f}", f"{now_time} 更新")
        c2.metric("监测状态", "正在追踪...", delta_color="normal")

        # 自动刷新逻辑
        if st.toggle("开启实时盯盘 (15s/次)", value=True):
            time.sleep(15)
            st.rerun()
