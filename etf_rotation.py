#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF三因子轮动看板生成器 (增强版)
因子: M动量(40%) + V相对低位(30%) + F资金流(30%)
大盘趋势择时: 强势满仓 / 中性半仓 / 弱势防御(自动缩放仓位)

新增功能(2026-08-06):
  1) 信号持续天数   —— 基于历史K线滚动计算"进入前N且风控通过"连续几天
  2) 历史回测最优持股天数 —— 信号触发后持有[1,3,5,10,20]天收益, 取均值最高区间
  3) 操作建议引擎   —— 左侧加仓 / 网格高抛低吸 / 持有 / 破位止损(含止损价+网格区间)

信号定义: 综合得分进入前N(中性前2)且三重风控通过
操作风格: 震荡市做网格高抛低吸 + 相对低位左侧加仓 + 破20日线或-5%止损

数据源: 新浪财经公开接口 (免费)
输出: docs/index.html (看板) + docs/history.json (历史记录)
本地用法:  python etf_rotation.py
GitHub Actions 每日19:00(北京时间)自动运行
"""
import json
import os
import datetime
import urllib.request
import urllib.error

# 与网格看板(grid_trading.py)统一行情判定口径
try:
    from grid_trading import analyze as grid_analyze
except ImportError:
    grid_analyze = None

# ===================== 参数区 (可改) =====================
MOMENTUM_SHORT = 10        # 动量短周期(天)
MOMENTUM_LONG  = 20        # 动量长周期(天)
V_PERIOD        = 60        # 价格分位窗口(天)
MA_PERIOD       = 20        # 均线周期
F_SHORT         = 5         # 资金流短周期(均量)
F_LONG          = 20        # 资金流长周期(均量)
WEIGHT          = 50        # 每只建议仓位(%基准, 已弃用, 改用大盘择时)
STOP_LOSS       = -5.0      # 止损线(%): 3日跌幅超此值 或 跌破20日线
W_M, W_V, W_F   = 0.4, 0.3, 0.3

HOLD_SIGNAL     = 2         # 信号定义: 综合前N(中性默认前2)且风控通过
BACKTEST_HOLDS  = [1, 3, 5, 10, 20]   # 回测持有期档位(天)
HISTORY_WINDOW  = 100       # 用于回测/信号天数回溯的交易日窗口
GRID_PCT        = 0.05      # 网格幅度 ±5%
MAX_HOLD        = 2         # 中性时持仓数量(展示用)

# ===================== 大盘趋势择时(仓位管理) =====================
MARKET_INDEX    = "sh000001"   # 大盘基准: 上证综指 (新浪代码)
BULL_WEIGHT     = 100   # 强势时建议总仓位(%)
NEUTRAL_WEIGHT  = 50    # 中性时建议总仓位(%)
BEAR_WEIGHT     = 20    # 弱势时建议总仓位(%)

# ===================== ETF池 (覆盖宽基/行业/海外/商品/债券) =====================
ETFS = [
    ("sh510010", "180治理ETF交银"),
    ("sh510020", "超大盘ETF博时"),
    ("sh510050", "上证50ETF华夏"),
    ("sh510090", "责任ETF建信"),
    ("sh510130", "上证中盘ETF易方达"),
    ("sh510140", "上证综指ETF华夏"),
    ("sh510160", "产业升级ETF南方"),
    ("sh510170", "大宗商品ETF国联安"),
    ("sh510180", "上证180ETF华安"),
    ("sh510200", "上证券商ETF汇安"),
    ("sh510210", "上证指数ETF富国"),
    ("sh510230", "金融ETF国泰"),
    ("sh510300", "沪深300ETF华泰柏瑞"),
    ("sh510410", "资源ETF博时"),
    ("sh510500", "中证500ETF南方"),
    ("sh510720", "红利国企ETF国泰"),
    ("sh510770", "G60创新ETF申万菱信"),
    ("sh510810", "上海国企ETF汇添富"),
    ("sh510880", "红利ETF华泰柏瑞"),
    ("sh510900", "恒生中国企业ETF易方达"),
    ("sh510990", "180ESGETF工银"),
    ("sh511600", "华安日日鑫ETF"),
    ("sh511660", "货币ETF建信"),
    ("sh511670", "华泰天天金ETF"),
    ("sh511690", "交易货币ETF大成"),
    ("sh511770", "金鹰增益货币ETF"),
    ("sh511800", "易方达货币ETF"),
    ("sh511820", "鹏华添利ETF"),
    ("sh511850", "招商财富宝ETF"),
    ("sh511880", "银华日利ETF"),
    ("sh511900", "富国货币ETF"),
    ("sh511910", "融通货币ETF"),
    ("sh511950", "添利货币ETF广发"),
    ("sh511970", "国寿货币ETF"),
    ("sh511990", "华宝添益ETF"),
    ("sh512000", "券商ETF华宝"),
    ("sh512010", "医药ETF易方达"),
    ("sh512030", "中证A50增强ETF易方达"),
    ("sh512070", "证券保险ETF易方达"),
    ("sh512090", "MSCIA股ETF易方达"),
    ("sh512100", "中证1000ETF南方"),
    ("sh512160", "MSCI中国A股ETF南方"),
    ("sh512170", "医疗ETF华宝"),
    ("sh512190", "浙商之江凤凰ETF"),
    ("sh512200", "房地产ETF南方"),
    ("sh512220", "TMTETF景顺"),
    ("sh512260", "中证500低波动ETF华安"),
    ("sh512330", "信息科技ETF南方"),
    ("sh512370", "A500增强ETF华夏"),
    ("sh512390", "中国低波ETF平安"),
    ("sh512400", "有色金属ETF南方"),
    ("sh512480", "半导体ETF国联安"),
    ("sh512530", "沪深300红利ETF建信"),
    ("sh512550", "富时A50ETF嘉实"),
    ("sh512580", "环保ETF广发"),
    ("sh512650", "长三角ETF汇添富"),
    ("sh512660", "军工ETF国泰"),
    ("sh512670", "国防ETF鹏华"),
    ("sh512690", "酒ETF鹏华"),
    ("sh512700", "XD银行ETF南方"),
    ("sh512710", "军工龙头ETF富国"),
    ("sh512750", "基本面50ETF嘉实"),
    ("sh512770", "战略新兴ETF华夏"),
    ("sh512800", "银行ETF华宝"),
    ("sh512870", "杭州湾区ETF南华"),
    ("sh512880", "证券ETF国泰"),
    ("sh512890", "红利低波ETF华泰柏瑞"),
    ("sh512930", "AI人工智能ETF平安"),
    ("sh512950", "央企改革ETF华夏"),
    ("sh512960", "央企结构调整ETF博时"),
    ("sh512970", "大湾区ETF平安"),
    ("sh512980", "传媒ETF广发"),
    ("sh513030", "德国ETF华安"),
    ("sh513050", "中概互联网ETF易方达"),
    ("sh513060", "恒生医疗ETF博时"),
    ("sh513070", "港股通消费ETF易方达"),
    ("sh513080", "法国ETF华安"),
    ("sh513090", "香港证券ETF易方达"),
    ("sh513120", "港股创新药ETF广发"),
    ("sh513170", "恒生央企ETF鹏华"),
    ("sh513180", "恒生科技ETF华夏"),
    ("sh513190", "港股通金融ETF华夏"),
    ("sh513200", "港股通医药ETF易方达"),
    ("sh513280", "恒生生物科技ETF汇添富"),
    ("sh513290", "纳指生物科技ETF汇添富"),
    ("sh513300", "纳斯达克ETF华夏"),
    ("sh513310", "中韩半导体ETF华泰柏瑞"),
    ("sh513320", "港股通新经济ETF易方达"),
    ("sh513330", "恒生互联网ETF华夏"),
    ("sh513360", "教育ETF博时"),
    ("sh513390", "纳指100ETF博时"),
    ("sh513400", "道琼斯ETF鹏华"),
    ("sh513500", "标普500ETF博时"),
    ("sh513520", "日经ETF华夏"),
    ("sh513530", "港股通红利ETF华泰柏瑞"),
    ("sh513550", "港股通50ETF华泰柏瑞"),
    ("sh513560", "香港科技ETF兴银"),
    ("sh513600", "恒生指数ETF南方"),
    ("sh513630", "港股低波红利ETF摩根"),
    ("sh513730", "东南亚科技ETF华泰柏瑞"),
    ("sh513750", "港股通非银ETF广发"),
    ("sh513770", "港股互联网ETF华宝"),
    ("sh513800", "日本东证指数ETF南方"),
    ("sh513850", "美国50ETF易方达"),
    ("sh513880", "日经225ETF华安"),
    ("sh513900", "港股通100ETF华安"),
    ("sh513920", "港股通央企红利ETF华安"),
    ("sh513950", "恒生红利ETF富国"),
    ("sh513970", "恒生消费ETF景顺"),
    ("sh513980", "港股科技ETF景顺"),
    ("sh513990", "港股通ETF招商"),
    ("sh515000", "科技ETF华宝"),
    ("sh515030", "新能源车ETF华夏"),
    ("sh515080", "中证红利ETF招商"),
    ("sh515090", "可持续发展ETF博时"),
    ("sh515150", "一带一路ETF富国"),
    ("sh515160", "MSCI中国ETF招商"),
    ("sh515200", "创新100ETF申万菱信"),
    ("sh515210", "钢铁ETF国泰"),
    ("sh515220", "煤炭ETF国泰"),
    ("sh515250", "智能汽车ETF富国"),
    ("sh515300", "300红利低波ETF嘉实"),
    ("sh515320", "电子50ETF华安"),
    ("sh515400", "大数据ETF富国"),
    ("sh515450", "红利低波50ETF南方"),
    ("sh515580", "科技100ETF华泰柏瑞"),
    ("sh515590", "500等权ETF前海开源"),
    ("sh515650", "消费50ETF富国"),
    ("sh515730", "家居家电ETF永赢"),
    ("sh515750", "科技50ETF富国"),
    ("sh515760", "浙江国资ETF华夏"),
    ("sh515790", "光伏ETF华泰柏瑞"),
    ("sh515800", "中证800ETF汇添富"),
    ("sh515880", "通信ETF国泰"),
    ("sh515900", "央企创新ETF博时"),
    ("sh515910", "质量ETF中金"),
    ("sh515920", "智能消费ETF博时"),
    ("sh515950", "医药50ETF富国"),
    ("sh516050", "科技龙头ETF工银"),
    ("sh516070", "低碳ETF易方达"),
    ("sh516110", "汽车ETF国泰"),
    ("sh516130", "消费龙头ETF华宝"),
    ("sh516150", "稀土ETF嘉实"),
    ("sh516160", "新能源ETF南方"),
    ("sh516320", "高端装备ETF华夏"),
    ("sh516380", "智能电动车ETF华宝"),
    ("sh516510", "云计算ETF易方达"),
    ("sh516520", "智能驾驶ETF华泰柏瑞"),
    ("sh516560", "养老ETF华宝"),
    ("sh516570", "石化ETF易方达"),
    ("sh516600", "消费服务ETF工银"),
    ("sh516620", "影视ETF国泰"),
    ("sh516670", "畜牧养殖ETF招商"),
    ("sh516800", "智能制造ETF华宝"),
    ("sh516820", "医疗创新ETF平安"),
    ("sh516830", "沪深300ESGETF富国"),
    ("sh516910", "物流ETF富国"),
    ("sh516970", "基建ETF广发"),
    ("sh516980", "证券先锋ETF华富"),
    ("sh517050", "互联网ETF华泰柏瑞"),
    ("sh517080", "沪港深500ETF汇添富"),
    ("sh517090", "央企共赢ETF国泰"),
    ("sh517180", "中国国企ETF南方"),
    ("sh517300", "沪港深300ETF国寿"),
    ("sh517330", "长江保护ETF易方达"),
    ("sh517350", "沪港深科技ETF广发"),
    ("sh517520", "黄金股ETF永赢"),
    ("sh517550", "沪港深消费龙头ETF招商"),
    ("sh517770", "游戏传媒ETF浦银"),
    ("sh517800", "人工智能50ETF方正富邦"),
    ("sh517850", "张江ETF汇添富"),
    ("sh517880", "品牌消费ETF华泰柏瑞"),
    ("sh517900", "银行AH优选ETF招商"),
    ("sh517950", "沪深港科技50ETF交银"),
    ("sh517990", "沪港深医药ETF招商"),
    ("sh520500", "恒生创新药ETF华泰柏瑞"),
    ("sh520510", "港股通医疗ETF华夏"),
    ("sh520550", "港股红利低波ETF招商"),
    ("sh520560", "香港大盘30ETF华宝"),
    ("sh520580", "新兴亚洲ETF招商"),
    ("sh520600", "港股通汽车ETF广发"),
    ("sh520750", "港股通信息ETF华富"),
    ("sh520770", "恒指港股通ETF建信"),
    ("sh520840", "港股通恒生科技ETF华安"),
    ("sh520870", "巴西ETF易方达"),
    ("sh520940", "港股通恒生ETF华安"),
    ("sh520990", "港股央企红利ETF景顺"),
    ("sh530380", "上证380ETF易方达"),
    ("sh530530", "上证580ETF华夏"),
    ("sh560030", "800价值ETF汇添富"),
    ("sh560050", "中国A50ETF汇添富"),
    ("sh560080", "中药ETF汇添富"),
    ("sh560120", "中证500现金流ETF华夏"),
    ("sh560170", "央企科技ETF南方"),
    ("sh560210", "农牧渔ETF景顺"),
    ("sh560280", "工程机械ETF广发"),
    ("sh560500", "500质量成长ETF鹏扬"),
    ("sh560570", "A500红利ETF国联安"),
    ("sh560660", "云计算50ETF新华"),
    ("sh560710", "船舶ETF富国"),
    ("sh560800", "数字经济ETF鹏扬"),
    ("sh560810", "央企ESGETF融通"),
    ("sh560860", "工业有色ETF万家"),
    ("sh560980", "光伏龙头ETF广发"),
    ("sh560990", "科技先锋ETF中金"),
    ("sh561060", "国企红利ETF华安"),
    ("sh561130", "国货ETF富国"),
    ("sh561200", "中证A100ETF工银"),
    ("sh561300", "沪深300增强ETF国泰"),
    ("sh561310", "消电ETF国泰"),
    ("sh561330", "矿业ETF国泰"),
    ("sh561360", "石油ETF国泰"),
    ("sh561420", "300现金流ETF汇添富"),
    ("sh561500", "漂亮50ETF华泰柏瑞"),
    ("sh561550", "中证500增强ETF华泰柏瑞"),
    ("sh561580", "央企红利ETF华泰柏瑞"),
    ("sh561780", "1000增强ETF博时"),
    ("sh561960", "央企回报ETF招商"),
    ("sh562000", "A100ETF华宝"),
    ("sh562010", "绿色能源ETF华宝"),
    ("sh562050", "药ETF华宝"),
    ("sh562060", "标普A股红利ETF华宝"),
    ("sh562070", "沪深300指增ETF华宝"),
    ("sh562180", "NA500红利低波ETF招商"),
    ("sh562310", "沪深300成长ETF银华"),
    ("sh562500", "机器人ETF华夏"),
    ("sh562520", "中证1000成长ETF华夏"),
    ("sh562530", "中证1000价值ETF华夏"),
    ("sh562550", "绿电ETF华夏"),
    ("sh562570", "信创ETF华夏"),
    ("sh562800", "稀有金属ETF嘉实"),
    ("sh562810", "上证指数增强ETF嘉实"),
    ("sh562850", "央企能源ETF嘉实"),
    ("sh562860", "疫苗ETF嘉实"),
    ("sh562910", "高端制造ETF易方达"),
    ("sh563010", "电信ETF易方达"),
    ("sh563060", "央企50ETF易方达"),
    ("sh563090", "上证50增强ETF易方达"),
    ("sh563210", "专精特新ETF富国"),
    ("sh563280", "A50增强ETF富国"),
    ("sh563300", "中证2000ETF华泰柏瑞"),
    ("sh563360", "A500ETF华泰柏瑞"),
    ("sh563390", "全指现金流ETF华泰柏瑞"),
    ("sh563510", "A500红利低波ETF易方达"),
    ("sh563560", "科技成长ETF兴业"),
    ("sh563580", "自由现金流800ETF万家"),
    ("sh563590", "A500红利低波动ETF国寿"),
    ("sh563700", "红利价值ETF易方达"),
    ("sh563780", "现金流全指ETF方正富邦"),
    ("sh563900", "300自由现金流ETF摩根"),
    ("sh563930", "上证增强ETF招商"),
    ("sh563960", "300质量ETF兴全"),
    ("sh563980", "800红利低波ETF鑫元"),
    ("sh563990", "800现金流ETF富国"),
    ("sh588000", "科创50ETF华夏"),
    ("sh588010", "科创新材料ETF博时"),
    ("sh588020", "科创成长ETF易方达"),
    ("sh588130", "科创医药ETF华夏"),
    ("sh588170", "科创半导体ETF华夏"),
    ("sh588200", "科创芯片ETF嘉实"),
    ("sh588220", "科创100ETF鹏华"),
    ("sh588230", "科创200ETF华泰柏瑞"),
    ("sh588320", "双创50增强ETF广发"),
    ("sh588330", "双创50ETF华宝"),
    ("sh588460", "科创50增强ETF鹏华"),
    ("sh588500", "科创100增强ETF易方达"),
    ("sh588550", "科创综指增强ETF易方达"),
    ("sh588710", "科创半导体设备ETF华泰柏瑞"),
    ("sh588760", "科创人工智能ETF广发"),
    ("sh588770", "科创信息ETF摩根"),
    ("sh588790", "科创AIETF博时"),
    ("sh588830", "科创新能源ETF鹏华"),
    ("sh588850", "科创机械ETF嘉实"),
    ("sh588910", "科创价值ETF建信"),
    ("sh589070", "科创芯片设计ETF天弘"),
    ("sh589280", "科创增强ETF华宝"),
    ("sh589680", "科创综指ETF鹏华"),
    ("sh589720", "科创创新药ETF国泰"),
    ("sz158008", "新能源电池ETF华夏"),
    ("sz159003", "招商快线ETF"),
    ("sz159005", "快钱ETF汇添富"),
    ("sz159015", "恒生港股通科技ETF国联"),
    ("sz159028", "港股汽车ETF天弘"),
    ("sz159036", "软件开发ETF华宝"),
    ("sz159066", "A股ETF建信"),
    ("sz159075", "工业互联网ETF华夏"),
    ("sz159102", "港股通生物科技ETF华安"),
    ("sz159106", "民企300ETF前海开源"),
    ("sz159107", "创业板软件ETF富国"),
    ("sz159108", "工业软件ETF博时"),
    ("sz159109", "恒生50ETF景顺"),
    ("sz159131", "港股通信息技术ETF华宝"),
    ("sz159141", "科创创业人工智能ETF永赢"),
    ("sz159151", "食品ETF华夏"),
    ("sz159159", "公用事业ETF国投瑞银"),
    ("sz159188", "红利100ETF景顺"),
    ("sz159201", "自由现金流ETF华夏"),
    ("sz159203", "大盘成长ETF博时"),
    ("sz159206", "卫星ETF永赢"),
    ("sz159207", "高股息ETF广发"),
    ("sz159209", "红利质量ETF招商"),
    ("sz159220", "港股通红利低波ETF华宝"),
    ("sz159226", "中证A500增强ETF国泰"),
    ("sz159227", "航空航天ETF华夏"),
    ("sz159235", "中证现金流ETF大成"),
    ("sz159259", "成长ETF易方达"),
    ("sz159262", "港股通科技ETF广发"),
    ("sz159263", "价值ETF易方达"),
    ("sz159267", "航天ETF华安"),
    ("sz159287", "创业板综ETF博时"),
    ("sz159289", "创业板综指ETF鹏华"),
    ("sz159290", "创业板综指增强ETF东财"),
    ("sz159292", "创业板综增强ETF华宝"),
    ("sz159295", "创业综指ETF西部利得"),
    ("sz159302", "港股高股息ETF银华"),
    ("sz159307", "红利低波100ETF博时"),
    ("sz159309", "油气ETF汇添富"),
    ("sz159326", "电网设备ETF华夏"),
    ("sz159329", "沙特ETF南方"),
    ("sz159331", "红利港股ETF国泰"),
    ("sz159335", "央企科创ETF融通"),
    ("sz159338", "中证A500ETF国泰"),
    ("sz159350", "深证50ETF富国"),
    ("sz159363", "创业板人工智能ETF华宝"),
    ("sz159366", "港股医疗ETF永赢"),
    ("sz159370", "创50ETF工银"),
    ("sz159377", "创业板医药ETF国泰"),
    ("sz159378", "通用航空ETF永赢"),
    ("sz159387", "创业板新能源ETF国泰"),
    ("sz159391", "大盘价值ETF博时"),
    ("sz159392", "航空ETF富国"),
    ("sz159399", "现金流ETF国泰"),
    ("sz159502", "标普生物科技ETF嘉实"),
    ("sz159506", "港股通创新药医疗ETF富国"),
    ("sz159509", "纳指科技ETF景顺"),
    ("sz159510", "沪深300价值ETF华夏"),
    ("sz159516", "半导体设备ETF国泰"),
    ("sz159517", "中证800增强ETF银华"),
    ("sz159518", "标普油气ETF嘉实"),
    ("sz159519", "港股国企ETF国泰"),
    ("sz159528", "国企改革ETF富国"),
    ("sz159529", "标普消费ETF景顺"),
    ("sz159545", "恒生红利低波ETF易方达"),
    ("sz159546", "集成电路ETF国泰"),
    ("sz159552", "中证2000增强ETF招商"),
    ("sz159565", "汽车零部件ETF易方达"),
    ("sz159566", "储能电池ETF易方达"),
    ("sz159570", "港股通创新药ETF汇添富"),
    ("sz159572", "创业板200ETF易方达"),
    ("sz159578", "深证主板50ETF南方"),
    ("sz159593", "中证A50ETF平安"),
    ("sz159601", "A50ETF华夏"),
    ("sz159605", "中概互联ETF广发"),
    ("sz159606", "中证500成长ETF易方达"),
    ("sz159611", "电力ETF广发"),
    ("sz159613", "信息安全ETF嘉实"),
    ("sz159616", "农牧ETF建信"),
    ("sz159617", "中证500价值ETF华夏"),
    ("sz159623", "成渝经济圈ETF博时"),
    ("sz159625", "绿色电力ETF嘉实"),
    ("sz159628", "国证2000ETF万家"),
    ("sz159636", "港股通科技30ETF工银"),
    ("sz159640", "碳中和龙头ETF工银"),
    ("sz159652", "有色ETF汇添富"),
    ("sz159653", "ESG300ETF国联安"),
    ("sz159659", "纳斯达克100ETF招商"),
    ("sz159662", "交运ETF南方"),
    ("sz159663", "机床ETF华夏"),
    ("sz159665", "半导体龙头ETF工银"),
    ("sz159666", "交通运输ETF华夏"),
    ("sz159667", "工业母机ETF国泰"),
    ("sz159676", "创业板增强ETF富国"),
    ("sz159678", "500增强ETF博时"),
    ("sz159680", "中证1000增强ETF招商"),
    ("sz159687", "亚太精选ETF南方"),
    ("sz159690", "有色矿业ETF招商"),
    ("sz159691", "港股红利ETF工银"),
    ("sz159698", "粮食ETF鹏华"),
    ("sz159707", "地产ETF华宝"),
    ("sz159717", "ESGETF鹏华"),
    ("sz159718", "港股医药ETF平安"),
    ("sz159719", "国企ETF平安"),
    ("sz159720", "智能车ETF泰康"),
    ("sz159725", "线上消费ETF工银"),
    ("sz159726", "港股通高股息ETF华夏"),
    ("sz159728", "在线消费ETF南方"),
    ("sz159732", "消费电子ETF华夏"),
    ("sz159735", "港股消费ETF银华"),
    ("sz159736", "食品饮料ETF天弘"),
    ("sz159743", "湖北ETF博时"),
    ("sz159745", "建材ETF国泰"),
    ("sz159750", "港股科技50ETF招商"),
    ("sz159755", "电池ETF广发"),
    ("sz159760", "医疗健康ETF泰康"),
    ("sz159761", "新材料ETF国泰"),
    ("sz159766", "旅游ETF富国"),
    ("sz159767", "电池龙头ETF兴银"),
    ("sz159773", "创业板科技ETF华泰柏瑞"),
    ("sz159777", "创科技ETF国联安"),
    ("sz159781", "科创创业ETF易方达"),
    ("sz159783", "科创创业50ETF华夏"),
    ("sz159786", "VRETF银华"),
    ("sz159790", "碳中和ETF华夏"),
    ("sz159791", "300ESGETF华夏"),
    ("sz159792", "港股通互联网ETF富国"),
    ("sz159804", "创中盘88ETF国寿"),
    ("sz159808", "创100ETF融通"),
    ("sz159811", "5GETF博时"),
    ("sz159814", "创业大盘ETF西部利得"),
    ("sz159819", "人工智能ETF易方达"),
    ("sz159822", "新经济ETF银华"),
    ("sz159825", "农业ETF富国"),
    ("sz159836", "创业板300ETF天弘"),
    ("sz159837", "生物科技ETF易方达"),
    ("sz159840", "锂电池ETF工银"),
    ("sz159850", "恒生国企ETF华夏"),
    ("sz159851", "金融科技ETF华宝"),
    ("sz159852", "软件ETF嘉实"),
    ("sz159856", "互联网龙头ETF工银"),
    ("sz159859", "生物医药ETF天弘"),
    ("sz159861", "碳中和50ETF国泰"),
    ("sz159865", "养殖ETF国泰"),
    ("sz159869", "游戏ETF华夏"),
    ("sz159870", "化工ETF鹏华"),
    ("sz159872", "智能网联汽车ETF鹏华"),
    ("sz159873", "医疗设备ETF天弘"),
    ("sz159883", "医疗器械ETF永赢"),
    ("sz159886", "机械ETF富国"),
    ("sz159892", "恒生医药ETF华夏"),
    ("sz159895", "物联网ETF易方达"),
    ("sz159901", "深证100ETF易方达"),
    ("sz159902", "中小100ETF华夏"),
    ("sz159903", "深成ETF南方"),
    ("sz159906", "深成长ETF大成"),
    ("sz159909", "TMT50ETF招商"),
    ("sz159910", "基本面120ETF嘉实"),
    ("sz159912", "深300ETF汇添富"),
    ("sz159913", "深价值ETF交银"),
    ("sz159915", "创业板ETF易方达"),
    ("sz159916", "基本面ETF建信"),
    ("sz159918", "中创400ETF嘉实"),
    ("sz159920", "恒生ETF华夏"),
    ("sz159928", "消费ETF汇添富"),
    ("sz159930", "能源ETF汇添富"),
    ("sz159936", "可选消费ETF广发"),
    ("sz159939", "信息技术ETF广发"),
    ("sz159940", "金融地产ETF广发"),
    ("sz159941", "纳指ETF广发"),
    ("sz159943", "深证成指ETF大成"),
    ("sz159944", "材料ETF广发"),
    ("sz159949", "创业板50ETF华安"),
    ("sz159959", "央企ETF银华"),
    ("sz159961", "深100ETF方正富邦"),
    ("sz159965", "央视50ETF国联"),
    ("sz159966", "创业板价值ETF华夏"),
    ("sz159967", "创业板成长ETF华夏"),
    ("sz159973", "民企ETF弘毅远方"),
    ("sz159976", "湾创ETF工银"),
    ("sz159991", "创业板大盘ETF招商"),
    ("sz159992", "创新药ETF银华"),
    ("sz159995", "芯片ETF华夏"),
    ("sz159996", "家电ETF国泰"),
    ("sz159997", "电子ETF天弘"),
    ("sz159998", "计算机ETF天弘"),
]

HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}

# ===================== 离线兜底快照 (无网络时使用) =====================
# 字段: code,name,price,day(+%),ten(+%),M,Vpct,Vsc,Fr,Fsc,total,pass
DEMO = [
    ("sz159915","创业板",3.368,3.00,-2.74,-8.27,8.7,91.3,1.36,68.0,44.49,False),
    ("sh510500","中证500",7.5,2.24,-0.07,-6.34,8.8,91.2,1.20,59.9,42.78,False),
    ("sh518880","黄金ETF",8.433,0.87,1.47,-0.22,10.1,89.9,0.99,49.4,41.72,False),
    ("sh512100","中证1000",2.864,2.36,-1.51,-8.06,8.2,91.8,1.14,56.9,41.37,False),
    ("sh588000","科创50",1.728,3.54,-4.37,-9.74,8.7,91.3,1.18,58.8,41.13,False),
    ("sh516160","新能源",2.436,0.87,3.66,-3.66,12.1,87.9,1.05,52.4,40.64,False),
    ("sh510300","沪深300",4.653,1.04,1.39,-0.99,12.7,87.2,0.98,48.9,40.45,False),
    ("sh512480","半导体",0.992,3.55,-7.29,-14.56,1.7,98.3,1.10,54.8,40.10,False),
    ("sh512660","军工",1.093,1.86,2.92,-4.64,8.8,91.2,0.94,46.9,39.58,False),
    ("sz159766","旅游",0.579,1.22,6.63,5.78,38.2,61.8,1.13,56.7,37.85,True),
    ("sh515050","电信",0.92,4.43,-12.71,-18.00,1.6,98.4,0.98,49.2,37.10,False),
    ("sh513100","纳指ETF",2.112,3.48,0.24,-0.87,21.9,78.1,0.70,35.1,33.60,False),
    ("sz159981","有色金属",1.485,-1.13,0.41,3.01,36.7,63.3,0.81,40.5,32.32,True),
    ("sh513500","标普500",2.509,1.21,0.24,0.24,39.9,60.1,0.93,46.7,32.14,False),
    ("sz159928","消费",0.697,-0.29,6.74,8.44,70.7,29.3,1.05,52.4,27.88,True),
    ("sh513180","恒生科技",0.609,0.00,3.92,5.09,60.4,39.6,0.86,43.1,26.85,True),
    ("sh512690","白酒",0.453,0.22,9.69,11.57,75.3,24.7,0.95,47.4,26.25,True),
    ("sh512800","银行",0.836,-0.48,5.96,8.34,96.2,3.8,1.07,53.4,20.47,True),
    ("sz159920","恒生ETF",1.522,-0.65,4.82,7.01,85.0,14.9,0.86,42.9,20.16,True),
    ("sh512070","证券",0.813,-0.37,3.17,2.15,86.6,13.4,0.74,36.9,15.97,True),
    ("sh512010","医药",0.377,0.27,3.57,3.69,96.6,3.4,0.68,34.0,12.70,True),
]


def fetch_kline(symbol, datalen=160):
    """从新浪财经抓取日K线, 返回按时间升序的 [{day,close,volume}]"""
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=%d" % (symbol, datalen))
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("gbk")
    data = json.loads(raw)
    rows = [{"day": d["day"], "open": float(d["open"]), "high": float(d["high"]),
             "low": float(d["low"]), "close": float(d["close"]), "volume": float(d["volume"])}
            for d in data]
    rows.sort(key=lambda x: x["day"])
    return rows


def compute_from(closes, vols):
    """根据截至某天的收盘价/成交量序列计算三因子与风控。序列长度需 >= V_PERIOD+1。"""
    n = len(closes)
    if n < V_PERIOD + 1:
        return None
    cur = closes[-1]
    prev = closes[-2] if n >= 2 else cur

    # M 动量: 近10日×60% + 近20日×40%
    p10 = closes[-1 - MOMENTUM_SHORT] if n > MOMENTUM_SHORT else closes[0]
    p20 = closes[-1 - MOMENTUM_LONG] if n > MOMENTUM_LONG else closes[0]
    r10 = (cur / p10 - 1) * 100
    r20 = (cur / p20 - 1) * 100
    m = r10 * 0.6 + r20 * 0.4

    # V 相对低位: 60日价格分位
    win = closes[-V_PERIOD:]
    lo, hi = min(win), max(win)
    v_pct = (cur - lo) / (hi - lo) * 100 if hi > lo else 50.0
    v_score = 100 - v_pct

    # F 资金流: 5日均量 / 20日均量 ×50
    if n >= F_LONG:
        f_ratio = (sum(vols[-F_SHORT:]) / F_SHORT) / (sum(vols[-F_LONG:]) / F_LONG)
    else:
        f_ratio = 1.0
    f_score = f_ratio * 50

    total = W_M * m + W_V * v_score + W_F * f_score

    # 三重风控
    ma_now = sum(closes[-MA_PERIOD:]) / MA_PERIOD
    ma_prev = sum(closes[-MA_PERIOD - 1:-1]) / MA_PERIOD
    p3 = closes[-4] if n >= 4 else closes[0]
    drop3 = (cur / p3 - 1) * 100
    rc1 = cur > ma_now
    rc2 = ma_now > ma_prev
    rc3 = drop3 >= STOP_LOSS
    passed = rc1 and rc2 and rc3

    return {
        "price": cur, "day_chg": (cur / prev - 1) * 100, "ten_chg": r10,
        "m": m, "v_pct": v_pct, "v_score": v_score,
        "f_ratio": f_ratio, "f_score": f_score, "total": total, "pass": passed,
        "ma20": ma_now,
    }


def compute(rows):
    """当日因子(用全序列尾部)"""
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]
    return compute_from(closes, vols)


def fetch_market_trend():
    """抓取大盘基准指数(上证综指), 判断趋势并给出建议总仓位。失败回退中性。"""
    try:
        rows = fetch_kline(MARKET_INDEX, datalen=70)
        closes = [r["close"] for r in rows]
        n = len(closes)
        cur = closes[-1]
        ma20 = sum(closes[-20:]) / 20.0
        ma60 = sum(closes[-60:]) / 60.0 if n >= 60 else sum(closes) / n
        mom20 = (cur / closes[-21] - 1) * 100 if n > 21 else 0.0
        bull = ma20 > ma60          # 多头排列(中线向上)
        above = cur > ma20          # 站上短期均线
        # 趋势得分: 多头0.5 + 站上均线0.3 + 动量正0.2
        score = (0.5 if bull else 0) + (0.3 if above else 0) + (0.2 if mom20 > 0 else 0)
        if score >= 0.7 and mom20 > 0:
            state, label, tw = "强势", "🟢 强势·看多", BULL_WEIGHT
        elif (not bull) and (not above) and mom20 < 0:
            state, label, tw = "弱势", "🔴 弱势·防御", BEAR_WEIGHT
        else:
            state, label, tw = "中性", "🟡 中性·震荡", NEUTRAL_WEIGHT
        return {"state": state, "label": label, "total_weight": tw,
                "close": cur, "ma20": ma20, "ma60": ma60,
                "mom20": mom20, "score": score, "ok": True}
    except Exception as e:
        print("  [大盘] 抓取失败, 按中性处理: %s" % e)
        return {"state": "中性", "label": "🟡 中性·震荡", "total_weight": NEUTRAL_WEIGHT,
                "close": None, "ma20": None, "ma60": None, "mom20": None,
                "score": None, "ok": False}


def fetch_all_rows():
    """抓取所有ETF的长K线(用于回测/信号天数)。返回 {code: rows|None}"""
    data = {}
    for code, name in ETFS:
        try:
            data[code] = fetch_kline(code, datalen=160)
        except Exception as e:
            print("  [跳过] %s 抓取失败: %s" % (code, e))
            data[code] = None
    return data


def build_matrix(all_rows):
    """构建每日因子矩阵: {code: [factor_or_None 每交易日]}"""
    matrix = {}
    for code, rows in all_rows.items():
        if not rows or len(rows) < V_PERIOD + 1:
            matrix[code] = [None] * (len(rows) if rows else 0)
            continue
        L = len(rows)
        facs = [None] * L
        for idx in range(V_PERIOD, L):
            closes = [r["close"] for r in rows[:idx + 1]]
            vols = [r["volume"] for r in rows[:idx + 1]]
            facs[idx] = compute_from(closes, vols)
        matrix[code] = facs
    return matrix


def daily_ranks(matrix, codes):
    """每日全市场排名: ranks[idx] = [(code, factor), ...] 按综合得分降序"""
    valid = [c for c in codes if matrix.get(c)]
    if not valid:
        return []
    L = min((len(matrix[c]) for c in valid))
    ranks = []
    for idx in range(L):
        day = [(c, matrix[c][idx]) for c in valid if matrix[c][idx] is not None]
        day.sort(key=lambda x: x[1]["total"], reverse=True)
        ranks.append(day)
    return ranks


def signal_days(ranks, matrix, codes):
    """信号持续天数: 从今天往前连续'进入前N且风控通过'的天数"""
    L = len(ranks)
    res = {c: 0 for c in codes}
    if L == 0:
        return res
    for c in codes:
        cnt = 0
        for idx in range(L - 1, max(-1, L - 1 - HISTORY_WINDOW), -1):
            if not (matrix.get(c) and idx < len(matrix[c]) and matrix[c][idx]):
                break
            day = ranks[idx]
            top = set(x[0] for x in day[:HOLD_SIGNAL])
            if c in top and matrix[c][idx]["pass"]:
                cnt += 1
            else:
                break
        res[c] = cnt
    return res


def backtest(ranks, matrix, code):
    """历史回测: 信号触发后持有[1,3,5,10,20]天收益, 取均值最高为最优持股天数"""
    facs = matrix.get(code)
    if not facs:
        return None
    L = len(ranks)
    maxk = max(BACKTEST_HOLDS)
    rets = {k: [] for k in BACKTEST_HOLDS}
    for idx in range(L):
        if idx + maxk >= L:
            break
        day = ranks[idx]
        top = set(x[0] for x in day[:HOLD_SIGNAL])
        fc = facs[idx]
        if fc is None or code not in top or not fc["pass"]:
            continue
        base = fc["price"]
        for k in BACKTEST_HOLDS:
            nxt = facs[idx + k]
            if nxt is None:
                continue
            rets[k].append((nxt["price"] / base - 1) * 100)
    if not rets[BACKTEST_HOLDS[0]]:
        return None
    avg = {k: (sum(v) / len(v) if v else 0.0) for k, v in rets.items()}
    win = {k: (sum(1 for x in v if x > 0) / len(v) * 100 if v else 0.0)
           for k, v in rets.items()}
    n = {k: len(v) for k, v in rets.items()}
    best = max(BACKTEST_HOLDS, key=lambda k: avg[k])
    return {"best": best, "avg": avg, "win": win, "n": n[BACKTEST_HOLDS[0]]}


def advice(fac, sig_days, bt, market, rows=None):
    """操作建议引擎: 左侧加仓 / 网格高抛低吸 / 持有 / 破位止损
    网格判定与网格看板(grid_trading.analyze)统一: 标的判震荡/滞涨才给网格,
    区间用60日箱体(非现价±5%), 止损=箱体下沿-5%, 两边看板信号一致"""
    if fac is None:
        return {"action": "—", "cls": "act-hold", "detail": "无数据",
                "stop": None, "glo": None, "ghi": None}
    v = fac["v_pct"]
    fr = fac["f_ratio"]
    pas = fac["pass"]
    price = fac["price"]
    ma20 = fac.get("ma20")
    stop = round(ma20, 3) if ma20 else round(price * (1 + STOP_LOSS / 100), 3)

    if not pas:
        if sig_days > 0:
            return {"action": "止损", "cls": "act-stop",
                    "detail": "持仓已破位(破均线或短期超跌), 参考止损价离场",
                    "stop": stop, "glo": None, "ghi": None}
        return {"action": "观望", "cls": "act-hold",
                "detail": "风控未通过, 暂不在买点, 观望等待",
                "stop": stop, "glo": None, "ghi": None}
    if v < 40 and fr > 1.0:
        return {"action": "加仓", "cls": "act-add",
                "detail": "相对低位(V%.0f%%) + 资金流入, 左侧分批加仓" % v,
                "stop": stop, "glo": None, "ghi": None}
    # 网格分支: 与网格看板同一判定函数, 同一箱体参数
    ga = None
    if rows and grid_analyze:
        try:
            ga = grid_analyze(rows)
        except Exception:
            ga = None
    if ga and ga["cls"] in ("range", "stag") and ga["grid"]:
        g = ga["grid"]
        return {"action": "网格", "cls": "act-grid",
                "detail": "%s箱体 %.3f~%.3f, %d格/步长%.2f%%, 破下沿-5%%止损"
                          % (ga["state"], g["lower"], g["upper"], g["n"], g["step_pct"]),
                "stop": g["stop"], "glo": g["lower"], "ghi": g["upper"]}
    return {"action": "持有", "cls": "act-hold",
            "detail": "趋势持有, 关注信号持续(%d天)" % sig_days,
            "stop": stop, "glo": None, "ghi": None}


def sgn(x, suf="%"):
    return ("+" if x >= 0 else "") + ("%.2f" % x) + suf


def render(records, now_str, live, market=None):
    # 大盘趋势默认中性
    if market is None:
        market = {"state": "中性", "label": "🟡 中性·震荡", "total_weight": NEUTRAL_WEIGHT,
                  "close": None, "ma20": None, "ma60": None, "mom20": None, "ok": False}

    # 按综合得分降序
    ranked = sorted(records, key=lambda r: r["total"], reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    # 持仓数量随大盘状态调整
    if market["state"] == "强势":
        hold_n = min(3, MAX_HOLD + 1)
    elif market["state"] == "弱势":
        hold_n = 1
    else:
        hold_n = MAX_HOLD
    passers = [r for r in ranked if r["pass"]]
    holds = passers[:hold_n]
    total_w = market["total_weight"]
    per = (total_w / len(holds)) if holds else 0

    # 卡片
    if holds:
        cards = "\n".join(
            _card_html(r, per, market) for r in holds
        )
    else:
        cards = '<div class="empty">⚠️ 今日无通过三重风控标的，建议空仓观望</div>'

    # 表格行
    rows_html = ""
    for r in ranked:
        hl = ' class="hl"' if r["pass"] else ""
        badge = ('<span class="badge pass">✅通过</span>' if r["pass"]
                 else '<span class="badge fail">❌未通过</span>')
        dcls = "pos" if r["day_chg"] >= 0 else "neg"
        tcls = "pos" if r["ten_chg"] >= 0 else "neg"
        adv = r.get("adv", {})
        act = adv.get("action", "—")
        act_cls = adv.get("cls", "act-hold")
        sig_d = r.get("sig_days", 0)
        bt = r.get("bt")
        bt_s = ("%d天" % bt["best"]) if bt else "—"
        bt_d = ("均%s" % sgn(bt["avg"][bt["best"]])) if bt else ""
        rows_html += (
            "<tr%s>\n"
            "  <td>%d</td><td class=\"code\">%s</td><td class=\"name\">%s</td>\n"
            "  <td>%.3f</td><td class=\"%s\">%s</td>\n"
            "  <td class=\"%s\">%s</td><td>%.2f</td>\n"
            "  <td>%.1f%%</td><td>%.1f</td>\n"
            "  <td>%.2f</td><td>%.1f</td>\n"
            "  <td class=\"total\">%.2f</td><td>%s</td>\n"
            "  <td>%s</td><td>%s<br><span class=\"td2\">%s</span></td><td class=\"%s\">%s</td>\n"
            "</tr>\n" % (
                hl, r["rank"], r["code"], r["name"], r["price"], dcls, sgn(r["day_chg"]),
                tcls, sgn(r["ten_chg"]), r["m"], r["v_pct"], r["v_score"],
                r["f_ratio"], r["f_score"], r["total"], badge,
                (str(sig_d) + "天") if sig_d > 0 else "—",
                bt_s, bt_d, act_cls, act)
        )

    # 历史记录
    hist = load_history()
    if holds:
        hold_str = " | ".join("%s(%.1f)" % (r["name"], r["total"]) for r in holds)
    else:
        hold_str = "空仓"
    entry = {
        "time": now_str, "holds": hold_str,
        "total": len(ranked), "pass": len(passers),
        "market": market["state"], "weight": total_w,
    }
    hist.append(entry)
    hist = hist[-30:]
    save_history(hist)

    hist_rows = "\n".join(
        "<tr>\n  <td>%s</td><td>%s</td><td>%d</td><td>%d</td><td>%s</td>\n</tr>" % (
            h["time"], h["holds"], h["total"], h["pass"],
            ("%s/%d%%" % (h.get("market", "—"), h.get("weight", 0))) if h.get("market") else "—")
        for h in reversed(hist[-10:])
    )

    # 大盘趋势展示块
    mcls = {"强势": "bull", "中性": "neutral", "弱势": "bear"}.get(market["state"], "neutral")
    def _fmt(x):
        return ("%.2f" % x) if isinstance(x, (int, float)) else "—"
    if market["mom20"] is None:
        mom_s = "—"
    else:
        mom_s = ("+" if market["mom20"] >= 0 else "") + "%.2f" % market["mom20"]
    market_html = (
        '<div class="mkt %s">📈 大盘趋势: <b>%s</b> | 上证综指 <b>%s</b> | '
        '20日线 %s | 60日线 %s | 20日动量 <b>%s%%</b> | 建议总仓位 <b>%d%%</b></div>' % (
            mcls, market["label"], _fmt(market["close"]), _fmt(market["ma20"]),
            _fmt(market["ma60"]), mom_s, market["total_weight"]))

    src = "新浪财经(实时)" if live else "新浪财经(离线快照)"
    html = TEMPLATE % (
        len(ranked), now_str, src, market_html, cards, rows_html, hist_rows,
    )
    return html, entry


def _card_html(r, per, market):
    adv = r.get("adv", {})
    sig_d = r.get("sig_days", 0)
    bt = r.get("bt")
    bt_s = ("历史最优持股 <b>%d天</b>(均收益 %+.1f%%, 胜率 %.0f%%)" % (
        bt["best"], bt["avg"][bt["best"]], bt["win"][bt["best"]])) if bt else "历史最优持股 —(样本不足)"
    stop_s = ("¥%.3f" % adv["stop"]) if adv.get("stop") else "—"
    grid_s = ("¥%.3f ~ %.3f" % (adv["glo"], adv["ghi"])) if adv.get("glo") else "—"
    return (
        '<div class="pcard">\n'
        '  <div class="prank">🏆 第%d名</div>\n'
        '  <div class="pname">%s <span class="pcode">(%s)</span></div>\n'
        '  <div class="pdetail">\n'
        '    <span>现价: <b>%.3f</b></span> |\n'
        '    <span class="fc-m">M: %.2f</span> |\n'
        '    <span class="fc-v">V: %.1f</span> |\n'
        '    <span class="fc-f">F: %.1f</span> |\n'
        '    <span>综合: <b class="fc-t">%.2f</b></span>\n'
        '  </div>\n'
        '  <div class="pw">💰 建议仓位: %d%%</div>\n'
        '  <div class="pr">✅ 三重风控通过 | 日涨跌: %s | 📅 信号持续: %d天</div>\n'
        '  <div class="op %s">🎯 操作: <b>%s</b> — %s</div>\n'
        '  <div class="opd">🛡 止损参考: %s%s</div>\n'
        '  <div class="opd">🔲 网格区间: %s</div>\n'
        '  <div class="opd">📊 %s</div>\n'
        '</div>' % (
            r["rank"], r["name"], r["code"], r["price"], r["m"], r["v_score"],
            r["f_score"], r["total"], round(per), sgn(r["day_chg"]), sig_d,
            adv.get("cls", "act-hold"), adv.get("action", "—"), adv.get("detail", ""),
            stop_s, " (20日线)" if r.get("ma20") else " (-5%%硬止损)",
            grid_s, bt_s)
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta name="description" content="ETF三因子轮动看板 - 动量M+相对低位V+资金流F+大盘择时+信号天数+回测+操作建议 - 每日自动更新">
<title>ETF三因子轮动看板 | 每日自动更新</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--bd:#30363d;--t:#c9d1d9;--td:#8b949e;--g:#3fb950;--r:#f85149;--y:#d29922;--b:#58a6ff;--tt:#e3b341;}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--t);padding:20px;}
.hd{text-align:center;margin-bottom:24px;}
.hd h1{font-size:30px;color:var(--b);margin-bottom:8px;}
.hd .sub{color:var(--td);font-size:14px;}
.hd .dt{color:var(--g);font-size:16px;margin-top:4px;}
.hd .auto{color:var(--y);font-size:12px;margin-top:4px;}
.gridlink{display:inline-block;margin-top:10px;padding:8px 20px;background:rgba(88,166,255,.15);border:1px solid var(--b);border-radius:8px;color:var(--b);font-size:14px;font-weight:600;text-decoration:none;}
.gridlink:hover{background:rgba(88,166,255,.32);}
.lg{display:flex;gap:24px;justify-content:center;margin-bottom:16px;font-size:12px;color:var(--td);flex-wrap:wrap;}
.pc{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap;justify-content:center;}
.pcard{background:var(--card);border:2px solid var(--g);border-radius:12px;padding:16px 24px;min-width:380px;text-align:center;}
.prank{color:var(--y);font-size:14px;font-weight:bold;margin-bottom:4px;}
.pname{font-size:22px;font-weight:bold;margin-bottom:8px;}
.pcode{font-size:14px;color:var(--td);}
.pdetail{font-size:13px;color:var(--td);margin-bottom:8px;}
.pw{color:var(--g);font-size:16px;font-weight:bold;margin-bottom:4px;}
.pr{font-size:12px;color:var(--td);}
.op{margin-top:8px;font-size:13px;padding:6px 10px;border-radius:8px;text-align:left;line-height:1.5;}
.op.add{background:rgba(63,185,80,0.12);border:1px solid var(--g);color:var(--g);}
.op.grid{background:rgba(88,166,255,0.12);border:1px solid var(--b);color:var(--b);}
.op.hold{background:rgba(210,153,34,0.10);border:1px solid var(--y);color:var(--y);}
.op.stop{background:rgba(248,81,73,0.12);border:1px solid var(--r);color:var(--r);}
.opd{font-size:12px;color:var(--td);margin-top:4px;text-align:left;}
.fc-m{color:var(--b);}.fc-v{color:var(--g);}.fc-f{color:var(--y);}.fc-t{color:var(--tt);}
.empty{background:var(--card);border:2px solid var(--y);border-radius:12px;padding:20px 40px;font-size:18px;color:var(--y);}
table{width:100%%;border-collapse:collapse;background:var(--card);border-radius:8px;overflow:hidden;font-size:13px;margin-bottom:24px;}
th{background:#21262d;color:var(--td);padding:10px 8px;text-align:center;font-weight:600;border-bottom:2px solid var(--bd);white-space:nowrap;}
td{padding:8px;text-align:center;border-bottom:1px solid var(--bd);}
tr.hl{background:rgba(63,185,80,0.1);}
tr.hl td{border-color:rgba(63,185,80,0.3);}
.code{color:var(--b);font-family:monospace;}.name{font-weight:600;}
.pos{color:var(--g);}.neg{color:var(--r);}.total{color:var(--tt);font-weight:bold;font-size:15px;}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;}
.pass{background:rgba(63,185,80,0.2);color:var(--g);}
.fail{background:rgba(248,81,73,0.15);color:var(--r);}
.warn{background:rgba(210,153,34,0.2);color:var(--y);}
.act-add{color:var(--g);font-weight:600;}
.act-grid{color:var(--b);font-weight:600;}
.act-hold{color:var(--y);font-weight:600;}
.act-stop{color:var(--r);font-weight:600;}
.td2{font-size:10px;color:var(--td);}
.mkt{display:flex;gap:16px;flex-wrap:wrap;justify-content:center;align-items:center;margin:8px auto 22px;padding:12px 20px;border-radius:10px;font-size:14px;max-width:920px;line-height:1.6;}
.mkt.bull{background:rgba(63,185,80,0.12);border:1px solid var(--g);color:var(--g);}
.mkt.neutral{background:rgba(210,153,34,0.12);border:1px solid var(--y);color:var(--y);}
.mkt.bear{background:rgba(248,81,73,0.12);border:1px solid var(--r);color:var(--r);}
.mkt b{color:var(--t);}
.ft{text-align:center;margin-top:24px;color:var(--td);font-size:12px;}
.tip{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:12px 16px;margin:16px 0;font-size:13px;color:var(--td);line-height:1.8;}
.tip b{color:var(--y);}
.hist-title{color:var(--b);font-size:18px;font-weight:bold;margin:24px 0 12px 0;text-align:center;}
.hist-table{font-size:12px;}
@media(max-width:768px){table{font-size:10px;}th,td{padding:5px 3px;}.lg{gap:8px;}.mkt{font-size:12px;}}
</style></head><body>
<div class="hd"><h1>📊 ETF三因子轮动看板</h1>
<div class="sub">动量M(40%%) + 相对低位V(30%%) + 资金流F(30%%) + 大盘择时 | %d只主流ETF全覆盖</div>
<div class="dt">📅 %s</div>
<div class="auto">⚡ 每个交易日19:00自动更新 | 数据源: %s</div>
<a class="gridlink" href="grid.html">🧮 打开网格交易看板 →</a></div>
<div class="lg">
<span>🟦 M=近10日×60%%+近20日×40%%</span>
<span>🟩 V=60日价格分位(越低分越高)</span>
<span>🟨 F=5日均量/20日均量×50</span>
</div>
%s
<div class="pc">%s</div>
<table><thead><tr>
<th>#</th><th>代码</th><th>名称</th><th>现价</th><th>日涨幅</th><th>10日收益</th>
<th>M得分</th><th>V分位</th><th>V得分</th><th>F比率</th><th>F得分</th><th>综合</th><th>风控</th>
<th>信号天数</th><th>最优持股</th><th>操作</th>
</tr></thead><tbody>%s</tbody></table>

<div class="hist-title">📋 历史推荐记录</div>
<table class="hist-table"><thead><tr>
<th>更新时间</th><th>推荐持仓</th><th>ETF总数</th><th>风控通过数</th><th>大盘/总仓</th>
</tr></thead><tbody>%s</tbody></table>

<div class="tip">
📌 <b>使用说明：</b>每天19:00后查看 → 先看顶部「大盘趋势」定总仓位 → 选综合前N名(仓位随大盘缩放) → 看「信号天数」判断是否已持仓/刚触发 → 看「最优持股」定持有周期 → 按「操作」标签执行(加仓/网格/持有/止损)<br>
📌 <b>信号天数：</b>综合进入前N(中性前2)且三重风控连续通过的天数。天数越长=趋势越稳；刚触发(1~2天)=新信号，可建仓观察。<br>
📌 <b>历史最优持股：</b>回测"信号触发后持有1/3/5/10/20天"的平均收益，取最高者为最优持股天数（样本不足时显示—）。<br>
📌 <b>操作标签：</b>🟢加仓=相对低位+资金流入，左侧分批；🔵网格=震荡区间分3档高抛低吸；🟡持有=趋势跟随；🔴止损=破均线或短期超跌，参考止损价离场。<br>
📌 <b>大盘择时：</b>强势🟢满仓(100%%,3只) / 中性🟡半仓(50%%,2只) / 弱势🔴防御(20%%,1只)。<br>
📌 <b>三重风控：</b>①价格站上20日均线 ②均线向上 ③3日跌幅≤5%%。止损参考=20日线(或-5%%硬止损)。
</div>
<div class="ft">
<p>⚡ 每个交易日19:00自动更新 | 数据源: 新浪财经(免费公开) | ⚠️ 仅供参考，投资有风险</p>
<p>策略: 综合前N + 大盘择时 | 信号天数 + 历史回测最优持股 + 加仓/网格/止损建议</p>
</div>
</body></html>
"""


def load_history():
    p = os.path.join(DOCS, "history.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history(hist):
    p = os.path.join(DOCS, "history.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


def main():
    global DOCS
    base = os.path.dirname(os.path.abspath(__file__))
    DOCS = os.path.join(base, "docs")
    os.makedirs(DOCS, exist_ok=True)

    now = datetime.datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")

    print("[1/5] 抓取大盘趋势 ...")
    market = fetch_market_trend()

    print("[2/5] 抓取全部ETF长K线(回测用) ...")
    all_rows = fetch_all_rows()
    live = any(v is not None for v in all_rows.values())
    if not live:
        print("  ⚠️ 实时数据全部抓取失败, 回退离线快照")
        all_rows = {c: None for c, _ in ETFS}

    print("[3/5] 构建因子矩阵 + 回测 + 信号天数 ...")
    codes = [c for c, _ in ETFS]
    if live:
        matrix = build_matrix(all_rows)
        ranks = daily_ranks(matrix, codes)
        sig = signal_days(ranks, matrix, codes)
        bt = {c: backtest(ranks, matrix, c) for c in codes}
    else:
        sig = {c: 0 for c in codes}
        bt = {c: None for c in codes}

    print("[4/5] 计算当日因子 + 操作建议 ...")
    records = []
    if live:
        for code, name in ETFS:
            rows = all_rows.get(code)
            if rows:
                f = compute(rows)
                    if f is not None:          # 增加非空判断
                        f["code"] = code
                        f["name"] = name
                        records.append(f)
    if not records:
        live = False
        for code, name in ETFS:
            try:
                d = next(x for x in DEMO if x[0] == code)
            except StopIteration:
                continue
            f = dict(zip(
                ["code", "name", "price", "day_chg", "ten_chg", "m",
                 "v_pct", "v_score", "f_ratio", "f_score", "total", "pass"],
                d))
            f["ma20"] = None
            records.append(f)

    for r in records:
        c = r["code"]
        r["sig_days"] = sig.get(c, 0)
        r["bt"] = bt.get(c)
        r["adv"] = advice(r, r["sig_days"], r["bt"], market, all_rows.get(c))

    print("[5/5] 生成看板 HTML ...")
    html, entry = render(records, now_str, live, market)
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("  看板已写入 docs/index.html")

    # 收益/回测看板 (独立网页, 三因子页面"那一个"入口指向它)
    bhtml = render_backtest(records, bt, now_str, live)
    with open(os.path.join(DOCS, "backtest.html"), "w", encoding="utf-8") as f:
        f.write(bhtml)
    print("  回测看板已写入 docs/backtest.html")

    # 回测样本统计(供日志)
    bt_n = sum((bt[c]["n"] if bt.get(c) else 0) for c in codes)
    print("✅ 完成 (%s) | 大盘:%s 总仓%d%% | 推荐:%s | 风控通过:%d/%d | 回测信号样本:%d" % (
        "实时" if live else "离线快照", market["state"], market["total_weight"],
        entry["holds"], entry["pass"], entry["total"], bt_n))


BACKTEST_TPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>ETF 收益/回测看板</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--bd:#30363d;--t:#c9d1d9;--td:#8b949e;--up:#f85149;--down:#3fb950;--b:#58a6ff;--y:#d29922;}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--t);padding:20px;max-width:1100px;margin:0 auto;}
.hd{text-align:center;margin-bottom:18px;}
.hd h1{font-size:26px;color:var(--b);}
.hd .sub{color:var(--td);font-size:13px;margin-top:6px;}
.hd .dt{color:var(--y);font-size:14px;margin-top:4px;}
.hd a{display:inline-block;margin:8px 6px 0;padding:8px 18px;border-radius:8px;text-decoration:none;font-weight:600;font-size:13px;}
.gridlink{background:rgba(88,166,255,.15);border:1px solid var(--b);color:var(--b);}
.tflink{background:rgba(210,153,34,.15);border:1px solid var(--y);color:var(--y);}
.tip{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:12px 16px;margin:14px 0;font-size:12.5px;color:var(--td);line-height:1.8;}
.tip b{color:var(--y);}
table{width:100%%;border-collapse:collapse;background:var(--card);border-radius:8px;overflow:hidden;font-size:13px;}
th{background:#21262d;color:var(--td);padding:9px 6px;text-align:center;font-weight:600;border-bottom:2px solid var(--bd);white-space:nowrap;}
td{padding:8px 6px;text-align:center;border-bottom:1px solid var(--bd);}
.code{color:var(--b);font-family:monospace;}.name{font-weight:600;}.best{color:var(--y);font-weight:bold;}
.up{color:var(--up);font-weight:600;}.down{color:var(--down);font-weight:600;}
.bars{display:flex;align-items:flex-end;gap:3px;height:50px;justify-content:center;}
.bar{width:10px;border-radius:2px 2px 0 0;min-height:2px;}
.ft{text-align:center;margin-top:18px;color:var(--td);font-size:12px;}
@media(max-width:768px){table{font-size:10px;}th,td{padding:5px 2px;}}
</style></head><body>
<div class="hd"><h1>📈 ETF 收益/回测看板</h1>
<div class="sub">三因子信号触发后，持有 1/3/5/10/20 天的平均收益与胜率（共 %s 只，样本=历史所有信号触发日）</div>
<div class="dt">📅 %s ｜ 数据源: %s</div>
<a class="tflink" href="index.html">📊 返回三因子看板</a>
<a class="gridlink" href="grid.html">🧮 打开网格交易看板 →</a></div>
<div class="tip">📌 <b>怎么看：</b>「最优持股」=回测中平均收益最高的持有天数；下方数字为各持有期<b>平均收益</b>（红涨绿跌，中国习惯），「最优胜率」为该持有期盈利样本占比。样本不足（无历史信号）的ETF不显示。本看板仅供研究，不构成投资建议。</div>
<table><thead><tr>
<th>#</th><th>代码</th><th>名称</th><th>最优持股</th>
<th>1天</th><th>3天</th><th>5天</th><th>10天</th><th>20天</th>
<th>最优胜率</th><th>样本</th><th>收益分布</th>
</tr></thead><tbody>
%s
</tbody></table>
<div class="ft"><p>⚡ 数据源: 新浪财经(免费公开) ｜ ⚠️ 历史回测不代表未来收益，投资有风险</p></div>
</body></html>"""


def render_backtest(records, bt, now_str, live):
    """收益/回测看板: 信号触发后持有[1,3,5,10,20]天平均收益与胜率(红涨绿跌, 中国习惯)"""
    rows = []
    for r in records:
        c = r["code"]
        b = bt.get(c)
        if not b or not b.get("n"):
            continue
        rows.append((r, b))
    rows.sort(key=lambda x: x[1]["avg"][x[1]["best"]], reverse=True)

    body = ""
    for i, (r, b) in enumerate(rows, 1):
        avg = b["avg"]; win = b["win"]; best = b["best"]
        maxabs = max(abs(v) for v in avg.values()) or 1
        bars = '<div class="bars">'
        for k in BACKTEST_HOLDS:
            v = avg.get(k, 0)
            h = abs(v) / maxabs * 44 + 3
            color = "var(--up)" if v >= 0 else "var(--down)"
            bars += ('<div class="bar" title="%d天 %+.1f%%" style="height:%.0fpx;background:%s"></div>'
                     % (k, v, h, color))
        bars += '</div>'

        def cell(k):
            v = avg.get(k, 0)
            cls = "up" if v >= 0 else "down"
            return '<td class="%s">%+.1f%%</td>' % (cls, v)
        body += (
            "<tr>\n"
            "  <td>%d</td><td class='code'>%s</td><td class='name'>%s</td>\n"
            "  <td class='best'>%d天</td>\n%s%s%s%s%s\n"
            "  <td>%.0f%%</td><td>%d</td><td>%s</td>\n</tr>\n" % (
                i, r["code"], r["name"], best,
                cell(1), cell(3), cell(5), cell(10), cell(20),
                win.get(best, 0), b["n"], bars)
        )

    src = "新浪财经(实时)" if live else "新浪财经(离线快照)"
    return BACKTEST_TPL % (now_str, src, len(rows), body)


if __name__ == "__main__":
    main()
