# ETF三因子轮动系统 - 云端每日自动更新版

> 每个交易日19:00自动更新，买家打开链接就看最新看板，永久免费运行

---

## 一、系统组成

```
etf-dashboard/
├── etf_rotation.py              # 主脚本（抓数据+算因子+生成看板）
├── .github/workflows/
│   └── daily-update.yml         # GitHub Actions定时任务（每天19:00自动跑）
├── docs/                        # GitHub Pages托管目录
│   ├── index.html               # 看板页面（自动生成）
│   └── history.json             # 历史记录（自动生成）
└── README.md                    # 本文件
```

---

## 二、部署5步走（照做就行）

### 第1步：注册GitHub账号
- 打开 https://github.com/signup
- 填用户名、邮箱、密码，注册（免费）
- 邮箱验证

### 第2步：新建仓库
1. 登录后点右上角 **+** → **New repository**
2. Repository name 填 `etf-dashboard`
3. 选 **Public**（公开，Pages才能用）
4. 勾选 **Add a README file**
5. 点 **Create repository**

### 第3步：上传3个文件
1. 在仓库页面点 **Add file** → **Upload files**
2. 把以下文件拖进去上传：
   - `etf_rotation.py`（主脚本）
   - `.github/workflows/daily-update.yml`（定时任务配置）
   - > 注意：`.github`是隐藏文件夹，Windows上传时直接把`.github`整个文件夹拖进去
3. 点 **Commit changes**

> 💡 如果浏览器上传不了`.github`文件夹，用这个方法：
> 1. 在仓库里点 **Create new file**
> 2. 文件名输入 `.github/workflows/daily-update.yml`
> 3. 把`daily-update.yml`的内容粘贴进去
> 4. 点 **Commit new file**

### 第4步：开启GitHub Pages
1. 进入仓库 → 点 **Settings** → 左侧 **Pages**
2. Source 选 **Deploy from a branch**
3. Branch 选 **main** / 文件夹选 **/docs**
4. 点 **Save**
5. 等待1-2分钟，刷新页面会显示：
   ```
   Your site is live at https://你的用户名.github.io/etf-dashboard/
   ```
6. 这个链接就是你的**公开看板地址**，发给买家就行

### 第5步：手动触发第一次运行
1. 进入仓库 → 点顶部 **Actions** 标签
2. 左侧选 **每日更新ETF看板**
3. 点右侧 **Run workflow** → **Run workflow**
4. 等2-3分钟运行完成
5. 回到你的Pages链接刷新，看板就出来了

---

## 三、运行机制

| 时间 | 动作 |
|------|------|
| 周一至周五 19:00 | GitHub Actions自动触发脚本 |
| 19:00-19:02 | 抓21只ETF数据→算三因子→生成HTML |
| 19:02-19:03 | 自动提交到仓库→Pages更新 |
| 19:03+ | 买家打开链接就是当天最新看板 |

> ⚠️ GitHub Actions的cron可能有5-15分钟延迟，属正常现象。如果需要更精确，可改cron时间为 `50 10 * * 1-5`（18:50触发）。

---

## 四、闲鱼卖点

| 优势 | 说明 |
|------|------|
| ✅ 每日自动更新 | 交易日19:00自动出最新看板 |
| ✅ 在线看板链接 | 买家打开链接就看，不用装软件 |
| ✅ 历史记录可查 | 底部展示历史推荐记录 |
| ✅ 三因子模型 | M动量+V低位+F资金流，比单因子强 |
| ✅ 三重风控+止损 | 均线突破+趋势向上+跌幅控制 |
| ✅ 21只主流ETF | 宽基+行业+海外+商品全覆盖 |
| ✅ 永久免费运行 | GitHub不收费，无续费无到期 |

---

## 五、常见问题

**Q：GitHub会封号吗？**
A：不会。Actions每月2000分钟免费额度，每天跑1次≈3分钟，一个月≈60分钟，远超够用。

**Q：数据源稳定吗？**
A：新浪财经公开接口，免费稳定。如遇接口变动，脚本中`HEADERS`已配置Referer，基本能用。

**Q：买家需要翻墙吗？**
A：`github.io`的Pages链接国内可直连，部分网络可能慢但能打开。如需更快的国内访问，可后续迁移到腾讯云/阿里云。

**Q：能改参数吗？**
A：能。编辑`etf_rotation.py`顶部的参数区：
- `MOMENTUM_SHORT`：动量短周期（默认10天）
- `MA_PERIOD`：均线周期（默认20天）
- `MAX_HOLD`：持仓数量（默认2只）
- `STOP_LOSS`：止损线（默认-5%）

**Q：想改成每周一更新？**
A：编辑`.github/workflows/daily-update.yml`，把cron改为 `0 11 * * 1`（仅周一）。

---

## 六、免责声明

本工具基于公开数据和经典量化理论，仅供学习参考，不构成投资建议。投资有风险，入市需谨慎。
