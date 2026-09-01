#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF 网格交易看板生成器
=====================
核心逻辑: 网格只在震荡市/高位滞涨区赚钱, 趋势市禁用。
所以第一前提是【判断行情状态】, 再决定操作方式/止损/加仓区。

判断体系(全部可量化):
  震荡六指标: ADX / 20日均线斜率 / 20日振幅 / 布林带宽分位 / RSI位置 / 均线缠绕度
  高位滞涨三信号: 60日涨幅>15% / 近20日不创新高 / 量价背离(放量不涨或价平量缩)

行情状态四类:
  趋势市(涨/跌)  —— 禁网格, 交给三因子动量策略
  震荡市        —— 网格主战场
  高位滞涨      —— 网格+减仓双用
  观望          —— 信号不足, 不动

网格参数(仅对震荡/滞涨标的生成):
  区间=近60日高低点(过宽则缩到30日) / 格数5-10(每格2~3%)
  底仓40% / 止损=下沿-5% / 突破停止线=上沿+1%

数据源: 新浪财经公开接口(免费, 标准库only)
输出: docs/grid.html
本地用法: python grid_trading.py
"""
import json
import time
import datetime
import urllib.request
import urllib.error

# ===================== 参数区(可改) =====================
ADX_TREND   = 25      # ADX>=此值判趋势市
ADX_RANGE   = 20      # ADX<此值倾向震荡
AMP_MAX     = 0.15    # 20日振幅小于15%为窄幅
GRID_STEP   = 0.025   # 网格目标步长 2.5%
GRID_MIN_N  = 5       # 最少格数
GRID_MAX_N  = 10      # 最多格数
BASE_POS    = 50      # 底仓(%), 长线不动吃趋势; 其余50%为浮动仓做网格
STOP_BUF    = 0.05    # 止损缓冲: 跌破区间下沿5%清仓
BREAK_BUF   = 0.01    # 突破上沿1%停止网格
STAG_GAIN   = 0.15    # 60日涨幅>15%才有"高位"前提
BOX_WIDE    = 0.25    # 60日区间宽于25%则改用30日区间

HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}

# ETF池 —— 与 etf_rotation.py 保持一致
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
MARKET_INDEX = "sh000001"


# ===================== 数据抓取 =====================
def fetch_kline(symbol, datalen=400):
    """新浪日K线, 返回升序 [{day,open,high,low,close,volume}]"""
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData?symbol=%s&scale=240&ma=no&datalen=%d" % (symbol, datalen))
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("gbk")
    data = json.loads(raw)
    rows = [{
        "day": d["day"], "open": float(d["open"]), "high": float(d["high"]),
        "low": float(d["low"]), "close": float(d["close"]), "volume": float(d["volume"]),
    } for d in data]
    rows.sort(key=lambda x: x["day"])
    return rows


def try_fetch(symbol, tries=2):
    for t in range(tries):
        try:
            r = fetch_kline(symbol)
            if len(r) >= 60:
                return r
        except Exception:
            pass
        if t < tries - 1:
            time.sleep(2)  # 重试前缓一缓, 防新浪456限流
    return None


# ===================== 指标计算 =====================
def ma(vals, n, i=None):
    """第i根(默认最后)的n日均线"""
    if i is None:
        i = len(vals) - 1
    if i < n - 1:
        return None
    return sum(vals[i - n + 1:i + 1]) / n


def rsi(closes, n=14):
    """Wilder RSI"""
    if len(closes) < n + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def adx(rows, n=14):
    """Wilder ADX, 返回 (adx, di+, di-)"""
    if len(rows) < n * 2 + 1:
        return 20.0, 0.0, 0.0
    trs, pdms, ndms = [], [], []
    for i in range(1, len(rows)):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        up, dn = rows[i]["high"] - rows[i - 1]["high"], rows[i - 1]["low"] - rows[i]["low"]
        pdms.append(up if up > dn and up > 0 else 0.0)
        ndms.append(dn if dn > up and dn > 0 else 0.0)
    str_ = sum(trs[:n]); spd = sum(pdms[:n]); snd = sum(ndms[:n])
    dxs = []
    for i in range(n, len(trs)):
        str_ = str_ - str_ / n + trs[i]
        spd = spd - spd / n + pdms[i]
        snd = snd - snd / n + ndms[i]
        if str_ == 0:
            continue
        pdi = 100 * spd / str_
        ndi = 100 * snd / str_
        den = pdi + ndi
        dxs.append(100 * abs(pdi - ndi) / den if den else 0)
    if len(dxs) < n:
        return 20.0, 0.0, 0.0
    a = sum(dxs[:n]) / n
    for i in range(n, len(dxs)):
        a = (a * (n - 1) + dxs[i]) / n
    return a, pdi, ndi


def lin_slope(vals, n):
    """近n日线性斜率(日均变化率%)"""
    if len(vals) < n:
        return 0.0
    seg = vals[-n:]
    xbar = (n - 1) / 2
    ybar = sum(seg) / n
    num = sum((i - xbar) * (seg[i] - ybar) for i in range(n))
    den = sum((i - xbar) ** 2 for i in range(n))
    slope = num / den if den else 0
    return slope / ybar * 100 if ybar else 0  # 每日%变化


def percentile(sorted_vals, v):
    """v 在升序序列中的分位(0-100)"""
    if not sorted_vals:
        return 50.0
    c = sum(1 for x in sorted_vals if x <= v)
    return c / len(sorted_vals) * 100


def backtest_grid(rows):
    """250日滚动箱体回测(改进版):
    - 每20个交易日按当时前60日高低点重定箱体(过宽缩30日)
    - 底仓50%长线持有吃趋势 + 浮动仓50%做正金字塔网格(越深的格份额越大)
    - 收盘跌破箱体下沿-5%: 全部清仓(含底仓), 冷却至下个重定日再建仓
    - 收盘突破上沿+1%: 浮动仓停止网格, 底仓继续持有
    输出: ret总收益% / ann年化% / mdd最大回撤% / calmar卡玛 / hold同期死拿% /
          trades成交 / sells套利 / stops止损次数 / breaks突破次数"""
    if len(rows) < 330:
        return None
    closes = [r["close"] for r in rows]
    n_all = len(rows)
    start = n_all - 250
    TOTAL = 100.0   # 名义总资金
    REBUILD = 20    # 箱体重定周期(交易日)

    cash = TOTAL
    base_hold = 0.0
    cell_hold = {}   # {格号: 份额}
    box = None
    equity = []
    trades = sells = stops = breaks = 0

    for i in range(start, n_all):
        c = closes[i]
        if box is None or (i - start) % REBUILD == 0:
            # —— 重定箱体日: 旧仓变现, 按新箱体重建(底仓+现价以下各格) ——
            pre = rows[max(0, i - 60):i]
            if len(pre) < 30:
                continue
            hi = max(r["high"] for r in pre)
            lo = min(r["low"] for r in pre)
            if (hi - lo) / lo > BOX_WIDE:
                hi = max(r["high"] for r in pre[-30:])
                lo = min(r["low"] for r in pre[-30:])
            width = (hi - lo) / lo
            n = max(GRID_MIN_N, min(GRID_MAX_N, round(width / GRID_STEP)))
            step = (hi - lo) / n
            levels = [lo + step * k for k in range(n + 1)]
            w = [1 + (n - 1 - k) * 0.5 for k in range(n)]  # 正金字塔: 深格份额大
            wsum = sum(w)
            box = {"levels": levels, "n": n, "w": w, "wsum": wsum,
                   "stop": lo * (1 - STOP_BUF), "brk": hi * (1 + BREAK_BUF),
                   "broke": False}
            cash += base_hold * c + sum(s * c for s in cell_hold.values())
            base_hold = (TOTAL * 0.5) / c
            cash -= TOTAL * 0.5
            cell_hold = {}
            for k in range(n):
                if levels[k] < c:
                    amt = TOTAL * 0.5 * w[k] / wsum
                    if cash >= amt:
                        cell_hold[k] = amt / levels[k]
                        cash -= amt
        elif c < box["stop"]:
            # —— 止损: 全部清仓(含底仓), box=None 冷却至下个重定日 ——
            cash += base_hold * c + sum(s * c for s in cell_hold.values())
            base_hold = 0.0
            cell_hold = {}
            box = None
            stops += 1
        else:
            if not box["broke"] and c > box["brk"]:
                box["broke"] = True   # 浮动停网格, 底仓续持吃趋势
                breaks += 1
            if not box["broke"]:
                lv, n = box["levels"], box["n"]
                for k in range(n):
                    if c < lv[k] and k not in cell_hold:            # 跌穿买价→买
                        amt = TOTAL * 0.5 * box["w"][k] / box["wsum"]
                        if cash >= amt:
                            cell_hold[k] = amt / lv[k]
                            cash -= amt
                            trades += 1
                    elif c >= lv[k + 1] and k in cell_hold:         # 涨破卖价→卖
                        cash += cell_hold[k] * lv[k + 1]
                        del cell_hold[k]
                        trades += 1
                        sells += 1
        equity.append(cash + base_hold * c + sum(s * c for s in cell_hold.values()))

    if not equity:
        return None
    ret = equity[-1] / TOTAL - 1
    hold_ret = closes[-1] / closes[start] - 1
    peak, mdd = equity[0], 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak)
    ann = ret  # 250交易日≈1年
    return {
        "ret": round(ret * 100, 2), "ann": round(ann * 100, 2),
        "mdd": round(mdd * 100, 2),
        "calmar": round(ann / mdd, 2) if mdd > 0.001 else None,
        "hold": round(hold_ret * 100, 2),
        "trades": trades, "sells": sells, "stops": stops, "breaks": breaks,
    }


def analyze(rows):
    """对单只ETK的K线做全面诊断, 返回指标+状态+网格参数"""
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    vols = [r["volume"] for r in rows]
    price = closes[-1]

    a, pdi, ndi = adx(rows)
    r14 = rsi(closes)
    slope20 = lin_slope([ma(closes, 20, i) or closes[i] for i in range(len(closes))][-30:], 10)

    # 20日振幅
    hi20, lo20 = max(highs[-20:]), min(lows[-20:])
    amp20 = (hi20 - lo20) / price

    # 布林带宽(20,2) 及历史分位
    bws = []
    for i in range(19, len(closes)):
        seg = closes[i - 19:i + 1]
        m = sum(seg) / 20
        sd = (sum((x - m) ** 2 for x in seg) / 20) ** 0.5
        if m:
            bws.append(4 * sd / m)
    bw_now = bws[-1] if bws else 0.05
    bw_pct = percentile(sorted(bws[-120:]), bw_now)

    # 均线缠绕度: 近20日 ma5/ma10/ma20 的离散度均值
    tangles = []
    for i in range(max(19, len(closes) - 20), len(closes)):
        m5, m10, m20 = ma(closes, 5, i), ma(closes, 10, i), ma(closes, 20, i)
        if m5 and m10 and m20 and closes[i]:
            tangles.append((max(m5, m10, m20) - min(m5, m10, m20)) / closes[i])
    tangle = sum(tangles) / len(tangles) if tangles else 0.05

    # ---- 滞涨信号 ----
    gain60 = (price / closes[-61] - 1) if len(closes) > 61 else 0
    hi_all = max(highs[:-1])  # 历史最高(不含今天)
    days_since_high = 0
    for i in range(len(highs) - 1, -1, -1):
        if highs[i] >= max(highs) * 0.999:
            days_since_high = len(highs) - 1 - i
            break
    v5 = sum(vols[-5:]) / 5
    v20 = sum(vols[-20:]) / 20
    chg10 = price / closes[-11] - 1 if len(closes) > 11 else 0
    vol_diverge = (v5 > v20 * 1.2 and abs(chg10) < 0.02) or (v5 < v20 * 0.7 and abs(chg10) < 0.03)

    # ---- 震荡得分(0-100, 六指标) ----
    s_adx = 100 if a < 15 else (30 + (25 - a) * 7 if a < 25 else 0)
    s_slope = 100 if abs(slope20) < 0.15 else (50 if abs(slope20) < 0.4 else 10)
    s_amp = 100 if amp20 < 0.10 else (60 if amp20 < AMP_MAX else 15)
    s_bw = max(0, 100 - bw_pct * 1.2)
    d_rsi = abs(r14 - 50)
    s_rsi = 100 if d_rsi < 10 else (60 if d_rsi < 20 else 20)
    s_tan = 100 if tangle < 0.012 else (55 if tangle < 0.025 else 15)
    range_score = round((s_adx + s_slope + s_amp + s_bw + s_rsi + s_tan) / 6, 1)

    # ---- 滞涨得分 ----
    stag_score = 0
    if gain60 > STAG_GAIN:
        stag_score += 34
    if days_since_high >= 15:
        stag_score += 33
    if vol_diverge:
        stag_score += 33

    # ---- 状态判定 ----
    mom20 = price / closes[-21] - 1 if len(closes) > 21 else 0
    if a >= ADX_TREND:
        state = "趋势上涨" if mom20 > 0 else "趋势下跌"
        cls = "trend"
    elif stag_score >= 67:
        state = "高位滞涨"
        cls = "stag"
    elif range_score >= 58 and a < ADX_TREND:
        state = "震荡市"
        cls = "range"
    else:
        state = "观望"
        cls = "watch"

    # ---- 网格参数(震荡/滞涨才生成) ----
    grid = None
    if cls in ("range", "stag"):
        hi60, lo60 = max(highs[-60:]), min(lows[-60:])
        if (hi60 - lo60) / price > BOX_WIDE and len(rows) >= 30:
            hi60, lo60 = max(highs[-30:]), min(lows[-30:])
        width = (hi60 - lo60) / lo60
        n = max(GRID_MIN_N, min(GRID_MAX_N, round(width / GRID_STEP)))
        step = (hi60 - lo60) / n
        levels = [round(lo60 + step * i, 4) for i in range(n + 1)]
        pos = (price - lo60) / (hi60 - lo60) if hi60 > lo60 else 0.5
        cur_cell = max(0, min(n - 1, int((price - lo60) / step))) if step else 0
        # 正金字塔份额: 越深的格买得越多 (格1最深=1+(n-1)*0.5, 最浅=1)
        pyr = [round(1 + (n - 1 - k) * 0.5, 1) for k in range(n)]
        # 开仓过滤: 120日分位判高低位 + 价格在箱体下部才开仓
        v120 = percentile(sorted(closes[-120:]), price)
        if v120 >= 50:
            entry = "⚠ 高位箱体(120日分位%.0f%%), 不建议新开网格" % v120
            entry_ok = False
        elif pos >= 0.5:
            entry = "⏳ 价格在箱体中上部, 等回调到下部再开"
            entry_ok = False
        else:
            entry = "✅ 低位箱体+价格在下部, 可开仓"
            entry_ok = True
        grid = {
            "upper": round(hi60, 4), "lower": round(lo60, 4),
            "n": n, "step_pct": round(step / lo60 * 100, 2),
            "levels": levels, "cur_cell": cur_cell, "pyr": pyr,
            "stop": round(lo60 * (1 - STOP_BUF), 4),
            "brk": round(hi60 * (1 + BREAK_BUF), 4),
            "zone": "下部(可买区)" if pos < 0.33 else ("上部(可卖区)" if pos > 0.66 else "中部(持有)"),
            "entry": entry, "entry_ok": entry_ok, "v120": round(v120, 0),
        }

    # ---- 网格回测(仅震荡/滞涨) ----
    bt_result = backtest_grid(rows) if cls in ("range", "stag") else None

    return {
        "price": price, "adx": round(a, 1), "rsi": round(r14, 1),
        "amp20": round(amp20 * 100, 1), "bw_pct": round(bw_pct, 0),
        "slope": round(slope20, 2), "tangle": round(tangle * 100, 2),
        "gain60": round(gain60 * 100, 1), "hi_days": days_since_high,
        "range_score": range_score, "stag_score": stag_score,
        "state": state, "cls": cls, "mom20": round(mom20 * 100, 2),
        "grid": grid, "bt": bt_result, "day": rows[-1]["day"],
    }


# ===================== HTML 渲染 =====================
def fmt_pct(x, signed=True):
    return ("%+.2f%%" % x) if signed else ("%.2f%%" % x)


def color_pct(x):
    c = "#f85149" if x > 0 else ("#3fb950" if x < 0 else "#8b949e")
    return '<span style="color:%s">%s</span>' % (c, fmt_pct(x))


def state_badge(cls, state):
    return '<span class="st %s">%s</span>' % (cls, state)


def grid_card(name, code, d):
    g = d["grid"]
    bt = d.get("bt")
    rows_html = ""
    for i in range(g["n"]):
        buy, sell = g["levels"][i], g["levels"][i + 1]
        cur = ' class="cur"' if i == g["cur_cell"] else ""
        rows_html += ("<tr%s><td>第%d格</td><td>%.3f</td><td>→</td><td>%.3f</td>"
                      "<td>买%s份</td><td>卖%s份</td></tr>\n"
                      % (cur, i + 1, buy, sell, g["pyr"][i], g["pyr"][i]))
    bt_html = ""
    if bt:
        calmar = ("卡玛%.2f" % bt["calmar"]) if bt.get("calmar") else "卡玛—"
        ev = []
        if bt["stops"]:
            ev.append('<b style="color:#f85149">止损%d次</b>' % bt["stops"])
        if bt["breaks"]:
            ev.append('<b style="color:#3fb950">突破%d次</b>' % bt["breaks"])
        ev_s = (" · " + "/".join(ev)) if ev else ""
        bt_html = ('<div class="bline">📊 250日回测(滚动箱体+金字塔+底仓): 网格 <b>%s</b> '
                   '(年化%s, 最大回撤%.1f%%, %s) vs 死拿 %s · 套利%d次%s</div>'
                   % (color_pct(bt["ret"]), fmt_pct(bt["ann"]), bt["mdd"], calmar,
                      color_pct(bt["hold"]), bt["sells"], ev_s))
    entry_cls = "eok" if g["entry_ok"] else "eno"
    return """
<div class="gcard">
  <div class="ghead">%s <span class="code">%s</span> %s
    <span class="gp">现价 %.3f · %s · 120日分位 %.0f%%</span></div>
  <div class="gmeta">
    <span>区间 <b>%.3f ~ %.3f</b></span>
    <span>分 <b>%d</b> 格 · 每格约 <b>%.2f%%</b></span>
    <span>结构 <b>底仓%d%% + 浮动%d%%金字塔</b></span>
    <span class="stop">止损 <b>%.3f</b>(破下沿-5%%清仓)</span>
    <span class="brk">突破 <b>%.3f</b>(停浮动仓, 底仓续持)</span>
  </div>
  <div class="entry %s">%s</div>
  %s
  <table class="gt"><tr><th>格</th><th>买价</th><th></th><th>卖价</th><th>到买价买</th><th>到卖价卖</th></tr>
  %s</table>
  <div class="gnote">当前处于 <b>%s</b>(第%d格)。底仓%d%%长线不动; 浮动仓: 跌穿买价按份额买、涨破卖价按份额卖, 越深的格买得越多。</div>
</div>""" % (name, code, state_badge(d["cls"], d["state"]), d["price"], g["zone"], g["v120"],
            g["lower"], g["upper"], g["n"], g["step_pct"], BASE_POS, 100 - BASE_POS,
            g["stop"], g["brk"], entry_cls, g["entry"], bt_html, rows_html,
            g["zone"], g["cur_cell"] + 1, BASE_POS)


def render(items, now_str, live, mkt):
    items.sort(key=lambda x: (0 if x["cls"] in ("range", "stag") else 1, -x["range_score"]))
    grids = [x for x in items if x["grid"]]
    n_range = sum(1 for x in items if x["cls"] == "range")
    n_stag = sum(1 for x in items if x["cls"] == "stag")
    n_trend = sum(1 for x in items if x["cls"] == "trend")
    n_watch = sum(1 for x in items if x["cls"] == "watch")

    body_rows = ""
    for d in items:
        badge = state_badge(d["cls"], d["state"])
        if d["grid"]:
            g = d["grid"]
            box = "%.3f~%.3f" % (g["lower"], g["upper"])
            cell = "%d格/%.2f%%" % (g["n"], g["step_pct"])
            stop = "%.3f" % g["stop"]
            op = '<span class="opb grid">网格</span>'
        elif d["cls"] == "trend":
            box = cell = stop = "—"
            op = '<span class="opb no">禁网格</span>'
        else:
            box = cell = stop = "—"
            op = '<span class="opb wait">观望</span>'
        if d.get("bt"):
            b = d["bt"]
            bt_cell = ("%s<br><span class='btsub'>死拿%s·回撤%.1f%%·套利%d</span>"
                       % (color_pct(b["ret"]), fmt_pct(b["hold"]), b["mdd"], b["sells"]))
            if b["stops"]:
                bt_cell += "<br><span class='btwarn'>止损%d次</span>" % b["stops"]
            if b["breaks"]:
                bt_cell += "<br><span class='btbrk'>突破%d次</span>" % b["breaks"]
        else:
            bt_cell = "—"
        body_rows += ("<tr><td>%s</td><td class='nm'>%s</td><td>%.3f</td>"
                      "<td>%s</td><td>%s</td><td>%.1f</td><td>%.1f</td><td>%s</td>"
                      "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>\n"
                      % (d["code"], d["name"], d["price"], color_pct(d["mom20"]),
                         badge, d["adx"], d["range_score"],
                         ("<b>%d</b>" % d["stag_score"]) if d["stag_score"] >= 67 else str(d["stag_score"]),
                         box, cell, stop, bt_cell, op,
                         '<span class="zone">%s</span>' % d["grid"]["zone"] if d["grid"] else "—"))

    cards = "\n".join(grid_card(x["name"], x["code"], x) for x in grids)
    if not cards:
        cards = '<div class="empty">当前没有处于震荡/滞涨的标的, 网格空仓等待。趋势市请用三因子动量看板。</div>'

    mkt_html = ""
    if mkt:
        if mkt["cls"] == "trend":
            if mkt["mom20"] > 0:
                gcls, gpos, gtip = "up", 30, "网格易卖飞: 只做滞涨板块箱体, 主力仓位交给三因子动量策略"
            else:
                gcls, gpos, gtip = "down", 20, "防假箱体接飞刀: 只做回测无止损的真箱体标的, 轻仓跑"
        elif mkt["cls"] == "range":
            gcls, gpos, gtip = "range", 100, "网格黄金期: 仓位可拉满, 按下方卡片参数机械执行"
        else:
            gcls, gpos, gtip = "watch", 50, "方向不明: 半仓试运行, 标的从严"
        mkt_html = ('<div class="mk %s"><b>🎚️ 大盘开关</b> 上证 %.2f · ADX %.1f · 20日动量 %s · 判定 %s '
                    '→ <b>网格总仓位 ≤ %d%%</b><br><span class="mktip">%s</span></div>'
                    % (gcls, mkt["price"], mkt["adx"], color_pct(mkt["mom20"]),
                       state_badge(mkt["cls"], mkt["state"]), gpos, gtip))

    src = "实时数据(新浪)" if live else "离线快照"
    return TEMPLATE % {
        "now": now_str, "src": src, "mkt": mkt_html, "base": BASE_POS,
        "n_range": n_range, "n_stag": n_stag, "n_trend": n_trend, "n_watch": n_watch,
        "rows": body_rows, "cards": cards, "n_grid": len(grids),
    }


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ETF网格交易看板</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--bd:#30363d;--t:#c9d1d9;--td:#8b949e;
--g:#3fb950;--r:#f85149;--y:#d29922;--b:#58a6ff;--p:#bc8cff;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--t);padding:20px;}
h1{font-size:22px;margin-bottom:4px;}
.sub{color:var(--td);font-size:13px;margin-bottom:16px;}
.mk{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:14px;line-height:1.7;}
.mk.up{border-left:5px solid var(--y);}
.mk.down{border-left:5px solid var(--r);}
.mk.range{border-left:5px solid var(--g);}
.mk.watch{border-left:5px solid var(--td);}
.mktip{font-size:12px;color:var(--td);}
.sum{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px;}
.sbox{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px 22px;text-align:center;min-width:130px;}
.sbox .n{font-size:28px;font-weight:700;}
.sbox .l{font-size:12px;color:var(--td);margin-top:2px;}
.st{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;white-space:nowrap;}
.st.range{background:rgba(88,166,255,.15);border:1px solid var(--b);color:var(--b);}
.st.stag{background:rgba(188,140,255,.15);border:1px solid var(--p);color:var(--p);}
.st.trend{background:rgba(63,185,80,.12);border:1px solid var(--g);color:var(--g);}
.st.watch{background:rgba(139,148,158,.12);border:1px solid var(--td);color:var(--td);}
.opb{display:inline-block;padding:2px 10px;border-radius:6px;font-size:12px;font-weight:600;}
.opb.grid{background:rgba(88,166,255,.15);color:var(--b);}
.opb.no{background:rgba(248,81,73,.12);color:var(--r);}
.opb.wait{background:rgba(139,148,158,.12);color:var(--td);}
.zone{font-size:12px;color:var(--y);}
.btsub{font-size:11px;color:var(--td);}
.btwarn{font-size:11px;color:var(--r);font-weight:600;}
.btbrk{font-size:11px;color:var(--g);font-weight:600;}
.bline{background:rgba(88,166,255,.07);border:1px solid var(--bd);border-radius:8px;padding:8px 14px;font-size:13px;margin-bottom:12px;}
.entry{padding:8px 14px;border-radius:8px;font-size:13px;font-weight:600;margin-bottom:12px;}
.entry.eok{background:rgba(63,185,80,.12);border:1px solid var(--g);color:var(--g);}
.entry.eno{background:rgba(210,153,34,.10);border:1px solid var(--y);color:var(--y);}
table{width:100%%;border-collapse:collapse;background:var(--card);border-radius:8px;overflow:hidden;font-size:13px;margin-bottom:24px;}
th{background:#21262d;color:var(--td);padding:10px 6px;text-align:center;font-weight:600;border-bottom:2px solid var(--bd);white-space:nowrap;}
td{padding:9px 6px;text-align:center;border-bottom:1px solid var(--bd);white-space:nowrap;}
td.nm{font-weight:600;}
tr:hover{background:rgba(88,166,255,.05);}
h2{font-size:17px;margin:26px 0 12px;color:var(--b);}
.gcard{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:18px 20px;margin-bottom:18px;}
.ghead{font-size:16px;font-weight:700;margin-bottom:10px;}
.ghead .code{color:var(--td);font-weight:400;font-size:13px;margin:0 6px;}
.ghead .gp{font-size:13px;color:var(--td);font-weight:400;margin-left:10px;}
.gmeta{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:var(--td);margin-bottom:12px;}
.gmeta b{color:var(--t);}
.gmeta .stop b{color:var(--r);}
.gmeta .brk b{color:var(--g);}
table.gt{font-size:12px;margin-bottom:10px;}
table.gt td,table.gt th{padding:5px 8px;}
table.gt tr.cur{background:rgba(210,153,34,.14);}
table.gt tr.cur td:first-child{color:var(--y);font-weight:700;}
.gnote{font-size:12px;color:var(--td);line-height:1.7;}
.empty{background:var(--card);border:2px solid var(--y);border-radius:12px;padding:24px;text-align:center;font-size:15px;color:var(--y);}
.tip{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:14px 18px;margin:18px 0;font-size:13px;color:var(--td);line-height:1.9;}
.tip b{color:var(--t);}
.foot{color:var(--td);font-size:12px;margin-top:20px;text-align:center;}
a{color:var(--b);text-decoration:none;}
</style></head><body>
<h1>🧮 ETF 网格交易看板</h1>
<div class="sub">📅 %(now)s · 数据源: %(src)s · <a href="index.html">← 返回三因子轮动看板</a></div>
%(mkt)s
<div class="sum">
  <div class="sbox"><div class="n" style="color:var(--b)">%(n_range)d</div><div class="l">震荡市(网格)</div></div>
  <div class="sbox"><div class="n" style="color:var(--p)">%(n_stag)d</div><div class="l">高位滞涨(网格)</div></div>
  <div class="sbox"><div class="n" style="color:var(--g)">%(n_trend)d</div><div class="l">趋势市(禁网格)</div></div>
  <div class="sbox"><div class="n" style="color:var(--td)">%(n_watch)d</div><div class="l">观望</div></div>
</div>
<div class="tip"><b>使用规则:</b>
① <b>网格第一前提</b>——只做「震荡市」和「高位滞涨」标的, 趋势市(ADX≥25)网格必亏, 坚决不碰;
② <b>结构</b>: 底仓%(base)s%%长线不动(吃趋势, 突破不卖飞) + 浮动仓正金字塔网格(越深的格买得越多, 摊低成本);
③ <b>开仓过滤</b>: 只做120日低分位箱体, 且价格回到箱体下部才开仓(卡片有✅/⏳/⚠标记);
④ <b>止损铁律</b>: 收盘跌破区间下沿5%% = 箱体失效, 全部清仓(含底仓), 等下一个箱体再开;
⑤ <b>突破处理</b>: 涨破区间上沿 = 浮动仓停网格, 底仓继续持有吃趋势;
⑥ 回测口径: 250日滚动箱体(每20日重定区间), 看总收益/最大回撤/卡玛, 别只看一两个月。</div>
<table>
<tr><th>代码</th><th>名称</th><th>现价</th><th>20日动量</th><th>行情状态</th><th>ADX</th><th>震荡分</th><th>滞涨分</th><th>网格区间</th><th>格数/步长</th><th>止损价</th><th>250日回测</th><th>操作</th><th>当前位置</th></tr>
%(rows)s
</table>
<h2>📐 网格明细 (%(n_grid)d 只可操作标的)</h2>
%(cards)s
<div class="foot">网格交易看板 · 每个交易日收盘后更新 · 判断仅供参考, 不构成投资建议</div>
</body></html>"""


# ===================== 主流程 =====================
def main():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    items, live = [], True
    mkt = None

    r = try_fetch(MARKET_INDEX)
    if r:
        mkt = analyze(r)
    for code, name in ETFS:
        rows = try_fetch(code)
        if not rows:
            live = False
            continue
        d = analyze(rows)
        d["code"] = code
        d["name"] = name
        items.append(d)
        time.sleep(0.6)  # 每只间隔0.6s, 48只约30s, 防新浪456限流

    if not items:
        print("数据抓取失败, 无网络?")
        return

    html = render(items, now, live and mkt is not None, mkt)
    with open("docs/grid.html", "w", encoding="utf-8") as f:
        f.write(html)
    n_grid = sum(1 for x in items if x["grid"])
    print("OK 数据日=%s 标的=%d 可网格=%d (震荡%d/滞涨%d) -> docs/grid.html"
          % (items[0]["day"], len(items), n_grid,
             sum(1 for x in items if x["cls"] == "range"),
             sum(1 for x in items if x["cls"] == "stag")))


if __name__ == "__main__":
    main()
