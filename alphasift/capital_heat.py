#encoding:gbk
"""
资金热度策略

策略逻辑：
1. 硬筛选：排除ST、成交额、换手率、量比、涨跌幅、价格范围
2. 多因子评分：动量、活跃度、流动性、主题热度、稳定性
3. 风险控制：追高风险、异常量比、高换手率
4. 组合分散：行业集中度控制
"""
import pandas as pd
import numpy as np
import talib
from datetime import datetime, timedelta
from xtquant import xtdata

# ==================== 策略参数配置 ====================
class StrategyParams:
    # 硬筛选参数
    EXCLUDE_ST = True
    AMOUNT_MIN = 300000000  # 最低成交额 3亿
    TURNOVER_RATE_MIN = 2.0  # 最低换手率 2%
    VOLUME_RATIO_MIN = 1.5   # 最低量比
    CHANGE_PCT_MIN = 1.0     # 最低涨幅 1%
    CHANGE_PCT_MAX = 9.5     # 最高涨幅 9.5%（避免涨停）
    PRICE_MIN = 3.0          # 最低价格 3元
    PRICE_MAX = 220.0        # 最高价格 220元
    
    # 因子权重
    FACTOR_WEIGHTS = {
        'momentum': 0.32,
        'activity': 0.28,
        'liquidity': 0.16,
        'theme_heat': 0.10,
        'stability': 0.10,
        'reversal': 0.04
    }
    
    # 评分曲线参数
    MOMENTUM_CHASE_START_PCT = 6.5
    MOMENTUM_CHASE_PENALTY_SLOPE = 12.0
    ACTIVITY_IDEAL_VOLUME_RATIO = 2.8
    ACTIVITY_HIGH_VOLUME_RATIO = 7.0
    ACTIVITY_IDEAL_TURNOVER_RATE = 6.0
    ACTIVITY_HIGH_TURNOVER_RATE = 18.0
    STABILITY_HOT_CHANGE_PCT = 8.5
    THEME_HEAT_OVERHEAT_SCORE = 92.0
    THEME_HEAT_OVERHEAT_PENALTY_SLOPE = 0.35
    
    # 风险参数
    CHASE_CHANGE_PCT = 9.3
    ABNORMAL_VOLUME_RATIO = 8.0
    HIGH_TURNOVER_RATE = 22.0
    
    # 组合参数
    MAX_OUTPUT = 5
    MAX_SAME_BUCKET = 1
    CONCENTRATION_PENALTY = 5.0
    
    # 行业风险桶
    INDUSTRY_BUCKETS = {
        '金融': ['券商', '银行', '保险'],
        'AI算力': ['AI算力', '算力', '数据中心', '服务器', '光模块'],
        '新能源': ['新能源', '光伏', '锂电', '电池', '储能'],
        '周期': ['钢铁', '煤炭', '有色', '化工'],
        '机器人': ['机器人', '减速器', '执行器', '伺服']
    }

# ==================== 全局变量 ====================
class ExtendedContext:
	pass
ctx = ExtendedContext()
ctx.g_params = StrategyParams()
ctx.g_selected_stocks = []
ctx.g_position_map = {}
ctx.g_acct_id = '666653814277'
ctx.g_last_rebalance_date = None
ctx.g_stock_sector = '沪深A股'
ctx.g_all_stocks = []

def init(ContextInfo):
	"""初始化函数"""
	print("资金热度策略初始化")
	
	# 下载历史数据
	ctx.g_all_stocks = ContextInfo.get_stock_list_in_sector(ctx.g_stock_sector)
	print(f"开始下载 {len(ctx.g_all_stocks)} 只股票的日线数据...")
	# 批量下载日线数据
	xtdata.download_history_data2(
		stock_list = ctx.g_all_stocks,
		period = '1d',
		progress_callback = progress_callback,
		start_time = '20200101',
		end_time=''
	)
	print(f'历史数据已下载：{len(ctx.g_all_stocks)}')

	count = xtdata.get_local_data_count()
	print(f"本地缓存数据量：{count}")
	
def progress_callback(data):
	"""实时进度监控"""
	print(f"进度: {data['finished']}/{data['total']} | 当前代码: {data['stockcode']}")
	
def handlebar(ContextInfo):
	if not ContextInfo.is_last_bar():
		return
		
	current_date = timetag_to_datetime(ContextInfo.get_bar_timetag(ContextInfo.barpos), "%Y%m%d")
	print(f'当前日期：{current_date}')

	# 每天只执行一次筛选（日线）
	if ctx.g_last_rebalance_date == current_date:
		return
	
	# 1. 获取全市场股票列表(如股票池超过一定数量，可用 down_history_data + get_local_data + get_full_tick 拼接历史和最新数据替代)
	# today_str = datetime.now().strftime('%Y%m%d')  # 实盘用当天，回测用 context.date
	stock_list = ContextInfo.get_stock_list_in_sector(ctx.g_stock_sector)
	if not stock_list:
		print("无法获取股票列表")
		return []

	print(f"开始筛选'{ctx.g_stock_sector}'，股票池规模: {len(stock_list)}")
	
	# 2. 获取快照数据
	try:
		# 获取当前行情快照
		snapshot = ContextInfo.get_market_data_ex(
			['close'], 
			stock_list, 
			period = '1d', 
			dividend_type = 'front_ratio', 
			count = 1,
			subscribe = False
		)
		
		if not snapshot:
			print("无法获取行情快照")
			return
	except Exception as e:
		print(f"获取快照失败: {e}")
		return
		
	print(f'数据已获取：{len(snapshot)}')
	
	# 执行筛选
	ctx.g_selected_stocks = screen_stocks(snapshot)
	# ctx.g_last_rebalance_date = current_date

	# if not context.selected_stocks:
		# print("未选出任何股票")
		# return

	# 执行交易逻辑
	# execute_trading(context)

def execute_trading(context):
	"""执行交易"""
	selected_codes = [stock['code'] for stock in context.selected_stocks]
	current_positions = get_position()

	# 卖出不在选中列表中的股票
	for pos in current_positions:
		code = pos['code']
		if code not in selected_codes:
			print(f"卖出 {code}")
			order(code, volume=pos['volume'], side=SELL)

	# 买入选中的股票（等权分配）
	if selected_codes:
		total_capital = get_account_info().get('total_assets', 1000000)
		position_size = total_capital / len(selected_codes)
		
		for stock in context.selected_stocks:
			code = stock['code']
			price = stock['price']
			
			if price <= 0:
				continue
			
			# 计算买入数量（取整到100股的倍数）
			volume = int((position_size / price) / 100) * 100
			
			if volume > 0:
				# 检查当前持仓
				current_vol = sum(p['volume'] for p in current_positions if p['code'] == code)
				
				if current_vol < volume:
					buy_vol = volume - current_vol
					print(f"买入 {code} {buy_vol}股")
					order(code, volume=buy_vol, side=BUY)

# ==================== 工具函数 ====================
def _is_st_stock(code):
	"""判断是否为ST股票"""
	try:
		info = get_stock_basic_info(code)
		if info and 'name' in info:
			name = info['name']
			return 'ST' in name or '*ST' in name or '退' in name
	except:
		pass
	return False

def _get_market_cap(code):
	"""获取总市值"""
	try:
		df = get_history_data(
			security_list=[code],
			start_time=get_current_time(),
			end_time=get_current_time(),
			fields=['market_cap']
		)
		if not df.empty:
			return df['market_cap'].iloc[0]
	except:
		pass
	return None

def _get_pe_pb(code):
	"""获取PE和PB"""
	try:
		# 尝试从基本面获取
		fundamentals = get_fundamentals(
			code,
			date=get_current_time(),
			fields=['pe_ttm', 'pb']
		)
		if fundamentals is not None and len(fundamentals) > 0:
			return fundamentals.get('pe_ttm'), fundamentals.get('pb')
	except:
		pass
	return None, None

def _get_industry(code):
	"""获取行业信息"""
	try:
		info = get_stock_basic_info(code)
		if info:
			return info.get('industry', ''), info.get('concepts', '')
	except:
		pass
	return '', ''

# ==================== 因子评分函数 ====================
def compute_momentum_score(df, params):
	"""计算动量因子得分（0-100）"""
	score = pd.Series(50.0, index=df.index)

	if 'change_pct' in df.columns:
		change = pd.to_numeric(df['change_pct'], errors='coerce').fillna(0)
		# 基础得分：涨幅越高越好，但超过阈值开始惩罚追高
		base_score = 60 + change * 5
		penalty = np.maximum(change - params.MOMENTUM_CHASE_START_PCT, 0) * params.MOMENTUM_CHASE_PENALTY_SLOPE
		intraday_score = base_score - penalty
		score = score * 0.35 + intraday_score.clip(5, 100) * 0.65

	return score.clip(0, 100)

def compute_activity_score(df, params):
	"""计算活跃度因子得分（0-100）"""
	score = pd.Series(50.0, index=df.index)

	if 'volume_ratio' in df.columns:
		volume_ratio = pd.to_numeric(df['volume_ratio'], errors='coerce').fillna(1.0)
		# 量比在理想值附近得分最高，过高开始惩罚
		vr_score = 100 - np.abs(volume_ratio - params.ACTIVITY_IDEAL_VOLUME_RATIO) * 15
		vr_penalty = np.maximum(volume_ratio - params.ACTIVITY_HIGH_VOLUME_RATIO, 0) * 8
		vr_score = vr_score - vr_penalty
		score = score * 0.45 + vr_score.clip(5, 100) * 0.55

	if 'turnover_rate' in df.columns:
		turnover = pd.to_numeric(df['turnover_rate'], errors='coerce').fillna(0)
		# 换手率在理想值附近得分最高
		turnover_score = 100 - np.abs(turnover - params.ACTIVITY_IDEAL_TURNOVER_RATE) * 8
		turnover_penalty = np.maximum(turnover - params.ACTIVITY_HIGH_TURNOVER_RATE, 0) * 5
		turnover_score = turnover_score - turnover_penalty
		turnover_score = np.where(turnover > 0, turnover_score, 40)
		score = score * 0.55 + turnover_score.clip(5, 100) * 0.45

	return score.clip(0, 100)

def compute_liquidity_score(df):
	"""计算流动性因子得分（0-100）"""
	if 'amount' not in df.columns:
		return pd.Series(50.0, index=df.index)

	amount = pd.to_numeric(df['amount'], errors='coerce')
	log_amount = np.log10(amount.clip(lower=1))

	# 横向排名得分
	valid_mask = amount > 0
	if valid_mask.any():
		ranks = log_amount[valid_mask].rank(pct=True) * 100
		score = pd.Series(20.0, index=df.index)
		score.loc[valid_mask] = ranks
		return score.clip(0, 100)

	return pd.Series(50.0, index=df.index)

def compute_stability_score(df, params):
	"""计算稳定性因子得分（0-100）"""
	score = pd.Series(78.0, index=df.index)

	if 'change_pct' in df.columns:
		change = pd.to_numeric(df['change_pct'], errors='coerce').fillna(0)
		# 波动越大扣分越多
		score -= np.minimum(np.abs(change), 10) * 3
		# 过热涨幅额外扣分
		hot_penalty = np.maximum(change - params.STABILITY_HOT_CHANGE_PCT, 0) * 5
		score -= hot_penalty

	if 'turnover_rate' in df.columns:
		turnover = pd.to_numeric(df['turnover_rate'], errors='coerce').fillna(0)
		high_turnover_penalty = np.maximum(turnover - 10, 0) * 2
		score -= high_turnover_penalty

	return score.clip(0, 100)

def compute_theme_heat_score(df, params):
	"""计算主题热度因子得分（0-100）"""
	score = pd.Series(50.0, index=df.index)

	# 尝试获取板块热度相关数据
	if 'industry_change_pct' in df.columns:
		change = pd.to_numeric(df['industry_change_pct'], errors='coerce').fillna(0)
		score = score + change * 6

	# 过热惩罚
	overheat = np.maximum(score - params.THEME_HEAT_OVERHEAT_SCORE, 0)
	score = score - overheat * params.THEME_HEAT_OVERHEAT_PENALTY_SLOPE

	return score.clip(0, 100)

def compute_reversal_score(df):
	"""计算反转因子得分（0-100）"""
	if 'change_pct' not in df.columns:
		return pd.Series(50.0, index=df.index)

	change = pd.to_numeric(df['change_pct'], errors='coerce').fillna(0)
	# 反转策略偏好小幅下跌，但此策略中权重很低
	score = 100 - np.abs(change + 3) * 13
	return score.clip(5, 100)

# ==================== 风险评估 ====================
def assess_risk(pick, params):
	"""评估单只股票的风险"""
	points = 0.0
	flags = []

	if pick['change_pct'] >= params.CHASE_CHANGE_PCT:
		points += 4.0
		flags.append('追高风险')

	if pick.get('volume_ratio') and pick['volume_ratio'] >= params.ABNORMAL_VOLUME_RATIO:
		points += 3.0
		flags.append('异常量比')

	if pick.get('turnover_rate') and pick['turnover_rate'] >= params.HIGH_TURNOVER_RATE:
		points += 3.0
		flags.append('高换手率')

	return points, flags

# ==================== 行业桶匹配 ====================
def get_industry_bucket(industry, concepts, buckets):
	"""获取股票所属的行业风险桶"""
	text = f"{industry} {concepts}"
	for bucket, keywords in buckets.items():
		if any(keyword in text for keyword in keywords):
			return bucket
	return '其他'

# ==================== 主筛选逻辑 ====================
def screen_stocks(snapshot):
	"""执行股票筛选"""

	# 3. 转换为DataFrame并添加必要字段
	df = snapshot.copy()
	print(f'df:{df}')

	# 4. 硬筛选
	mask = pd.Series(True, index=df.index)
	print(f'mask:{mask}')
'''
	# 排除ST
	if params.EXCLUDE_ST:
		mask &= ~df.index.map(_is_st_stock)

	# 成交额筛选
	if 'amount' in df.columns:
		mask &= pd.to_numeric(df['amount'], errors='coerce') >= params.AMOUNT_MIN

	# 换手率筛选
	if 'turnover_rate' in df.columns:
		mask &= pd.to_numeric(df['turnover_rate'], errors='coerce') >= params.TURNOVER_RATE_MIN

	# 量比筛选
	if 'volume_ratio' in df.columns:
		mask &= pd.to_numeric(df['volume_ratio'], errors='coerce') >= params.VOLUME_RATIO_MIN

	# 涨跌幅筛选
	if 'change_pct' in df.columns:
		change = pd.to_numeric(df['change_pct'], errors='coerce')
		mask &= change >= params.CHANGE_PCT_MIN
		mask &= change <= params.CHANGE_PCT_MAX

	# 价格筛选
	if 'close' in df.columns:
		price = pd.to_numeric(df['close'], errors='coerce')
		mask &= price >= params.PRICE_MIN
		mask &= price <= params.PRICE_MAX

	df_filtered = df[mask]
	print(f"硬筛选后剩余: {len(df_filtered)} 只股票")

	if df_filtered.empty:
		return []

	# 5. 计算因子得分
	factor_scores = {}
	factor_scores['momentum'] = compute_momentum_score(df_filtered, params)
	factor_scores['activity'] = compute_activity_score(df_filtered, params)
	factor_scores['liquidity'] = compute_liquidity_score(df_filtered)
	factor_scores['stability'] = compute_stability_score(df_filtered, params)
	factor_scores['theme_heat'] = compute_theme_heat_score(df_filtered, params)
	factor_scores['reversal'] = compute_reversal_score(df_filtered)

	# 6. 计算综合得分
	total_weight = sum(params.FACTOR_WEIGHTS.values())
	normalized_weights = {k: v/total_weight for k, v in params.FACTOR_WEIGHTS.items()}

	df_filtered['screen_score'] = 0.0
	for factor, weight in normalized_weights.items():
		if factor in factor_scores:
			df_filtered['screen_score'] += factor_scores[factor] * weight

	df_filtered['screen_score'] = df_filtered['screen_score'].clip(0, 100)

	# 7. 获取行业信息并评估风险
	results = []
	for code, row in df_filtered.iterrows():
		industry, concepts = _get_industry(code)
		risk_points, risk_flags = assess_risk(row.to_dict(), params)
		
		results.append({
			'code': code,
			'name': row.get('name', ''),
			'price': row.get('close', 0),
			'change_pct': row.get('change_pct', 0),
			'amount': row.get('amount', 0),
			'turnover_rate': row.get('turnover_rate', 0),
			'volume_ratio': row.get('volume_ratio', 0),
			'industry': industry,
			'concepts': concepts,
			'screen_score': row['screen_score'],
			'risk_points': risk_points,
			'risk_flags': risk_flags,
			'final_score': row['screen_score'] - min(risk_points, 12)  # 风险扣分，最多扣12分
		})

	# 8. 排序并应用组合分散
	results.sort(key=lambda x: x['final_score'], reverse=True)

	# 行业集中度控制
	bucket_counts = {}
	selected = []

	for item in results:
		bucket = get_industry_bucket(item['industry'], item['concepts'], params.INDUSTRY_BUCKETS)
		count = bucket_counts.get(bucket, 0)
		
		if count < params.MAX_SAME_BUCKET:
			selected.append(item)
			bucket_counts[bucket] = count + 1
		else:
			# 超过限制，扣除集中度惩罚分
			item['final_score'] -= params.CONCENTRATION_PENALTY

	# 9. 取前N只
	selected = sorted(selected, key=lambda x: x['final_score'], reverse=True)[:params.MAX_OUTPUT]

	print(f"最终选出 {len(selected)} 只股票")
	for i, item in enumerate(selected, 1):
		print(f"{i}. {item['code']} {item['name']} - 得分: {item['final_score']:.1f}")
	
	return selected
	'''

