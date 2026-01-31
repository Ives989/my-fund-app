import os
import sys
import pathlib
import shutil

# --- 1. 核心修复：解决云端只读权限与缓存问题 ---
os.environ['EF_CACHE_DIR'] = '/tmp/efinance_cache'

def mock_mkdir(*args, **kwargs):
    pass
pathlib.Path.mkdir = mock_mkdir

# --- 2. 导入依赖库 ---
import streamlit as st
import pandas as pd
import efinance as ef
import requests
import re
import json
import time
import plotly.graph_objects as go
from datetime import datetime

# --- 3. 手机端样式优化 ---
st.set_page_config(page_title="智投看板 Pro 2.0", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; border: 1px solid #eeeeee; padding: 15px; border-radius: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .main .block-container { padding-top: 1rem; }
    div[data-testid="stExpander"] { border: none !important; }
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { background-color: #f0f2f6; border-radius: 10px; padding: 10px 20px; }
    </style>
    """, unsafe_allow_html=True)

# --- 4. 数据存储逻辑 ---
DB_FILE = "portfolio.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return []
    return []

def save_data(data):
    with open(DB_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)

# --- 5. 养基宝同款：深度拟合算法 ---
@st.cache_data(ttl=15)
def fetch_official(code):
    """官方估值接口 (搬运工模式)"""
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
def fetch_shadow_v2(code):
    """影子估值 2.0 (拟合算法模式)"""
    try:
        # A. 抓取季报前十大
        url = f"http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=10"
        df = pd.read_html(url)[0]
        df['代码'] = df['股票代码'].astype(str).str.zfill(6)
        df['权重'] = df['持仓占比'].str.replace('%', '').astype(float)
        
        # B. 获取重仓股实时波动
        stock_codes = df['代码'].tolist()
        quotes = ef.stock.get_quote(stock_codes)
        merged = pd.merge(df, quotes[['股票代码', '涨跌幅']], left_on='代码', right_on='股票代码')
        
        # C. 计算前十大贡献
        top10_weight = merged['权重'].sum()
        top10_profit = (merged['权重'] * merged['涨跌幅']).sum() / 100
        
        # D. 板块风格对冲：判断是成长型还是价值型
        market_data = ef.stock.get_quote(['000300', '399006']) # 沪深300 vs 创业板指
        hs300 = market_data[market_data['股票代码'] == '000300']['涨跌幅'].values[0]
        cyb = market_data[market_data['股票代码'] == '399006']['涨跌幅'].values[0]
        
        # 寻找“成长股”关键词进行锚定切换
        growth_keywords = '宁德|阳光|药明|隆基|比亚迪|迈瑞|东方财富'
        is_growth = merged['股票名称'].str.contains(growth_keywords).any()
        anchor_index = cyb if is_growth else hs300
        
        # E. 最终公式：(前十大贡献 + 剩余仓位*锚定指数) * 0.95(实战平均仓位)
        remain_weight = 100 - top10_weight
        raw_estimate = top10_profit + (remain_weight * anchor_index / 100)
        final_estimate = raw_estimate * 0.95
        
        return round(final_estimate, 2)
    except Exception as e:
        return 0.0

# --- 6. 主界面 ---
st.title("🛡️ 智投看板 2.0")

tab_home, tab_manage = st.tabs(["📊 深度行情", "⚙️ 持仓管理"])

with tab_manage:
    with st.expander("➕ 添加新基金"):
        c_code = st.text_input("基金代码 (如 005827)")
        c_name = st.text_input("简称 (如 易方达蓝筹)")
        c_shares = st.number_input("持有份额", min_value=0.0, step=100.0)
        if st.button("💾 保存持仓"):
            if c_code and c_name:
                curr = load_data()
                curr.append({"code": c_code, "name": c_name, "shares": c_shares})
                save_data(curr)
                st.success("已同步至云端！")
                time.sleep(1)
                st.rerun()
    
    if st.button("🗑️ 清空所有基金"):
        save_data([])
        st.rerun()

with tab_home:
    portfolio = load_data()
    if not portfolio:
        st.info("👆 请先在‘持仓管理’中添加您的基金明细。")
    else:
        # 核心功能：模式切换
        mode = st.radio("数据模式", ["官方快速估值 (天天基金)", "影子拟合估值 (养基宝逻辑)"], horizontal=True)
        
        results = []
        with st.spinner('计算深度拟合数据中...'):
            for f in portfolio:
                if "官方" in mode:
                    d = fetch_official(f['code'])
                    if d:
                        profit = (d['val'] - d['last']) * f['shares']
                        results.append({"基金": f['name'], "涨跌%": d['change'], "预计盈亏": profit, "类型": "官方"})
                else:
                    s_change = fetch_shadow_v2(f['code'])
                    results.append({"基金": f['name'], "涨跌%": s_change, "预计盈亏": 0.0, "类型": "影子"})

        if results:
            df_res = pd.DataFrame(results)
            
            # 指标展示
            total_p = df_res['预计盈亏'].sum()
            avg_c = df_res['涨跌%'].mean()
            c1, c2 = st.columns(2)
            c1.metric("今日汇总 (估)", f"¥{total_p:,.2f}", f"{avg_c:+.2f}%")
            c2.metric("当前模式", "影子拟合" if "影子" in mode else "官方同步")

            # 收益分布图
            fig = go.Figure(go.Bar(
                x=df_res['基金'], y=df_res['涨跌%'],
                marker_color=['#ef553b' if x >= 0 else '#00cc96' for x in df_res['涨跌%']]
            ))
            fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

            # 明细表格
            st.dataframe(df_res.drop(columns=['类型']), use_container_width=True)

            if st.toggle("⏱️ 开启自动刷新盯盘", value=True):
                time.sleep(15)
                st.rerun()
