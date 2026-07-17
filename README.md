# GitHub Actions 可扩展 RSS 中转

这个仓库按计划从一个或多个源站抓取 RSS/Atom，必要时转换为标准 RSS 2.0，再通过 GitHub Pages 提供稳定的公开订阅地址。它适合解决：

- 服务器无法访问源站，但 GitHub Actions 可以访问；
- 源站要求特定 `User-Agent`、`Referer`、Cookie 预热或其他请求头；
- 原始 Atom/RSS 格式不够标准，需要先规范化；
- 以后继续增加其他有问题的订阅源。

## 一、最终工作方式

```text
源站 RSS/Atom -> GitHub Actions 定时抓取 -> 校验/规范化 -> GitHub Pages -> 订阅
```

以 GitHub 用户名 `alice`、仓库名 `rss-relay` 为例，配置中的：

```yaml
output: feeds/spj-journalremotesensing.xml
```

最终地址通常是：

```text
https://alice.github.io/rss-relay/feeds/spj-journalremotesensing.xml
```

## 二、建立仓库

1. 登录 GitHub，右上角选择 **New repository**。
2. Repository name 填 `rss-relay`。
3. 建议先选 **Public**。GitHub Free 可为公开仓库使用 Pages；私有仓库能否使用 Pages 取决于账户或组织方案。无论仓库是否私有，发布出来的 Pages 内容都应当按公开内容处理。
4. 不需要勾选自动生成 README、`.gitignore` 或 License，点击 **Create repository**。
5. 下载本模板并解压，在模板目录执行：

   ```bash
   git init
   git add .
   git commit -m "Initial RSS relay"
   git branch -M main
   git remote add origin https://github.com/你的用户名/rss-relay.git
   git push -u origin main
   ```

   如果你不用本地 Git，也可以在 GitHub 仓库页面选择 **Add file > Upload files**，上传模板内的全部文件。要确认隐藏目录 `.github/workflows/` 也被上传；网页逐个上传时容易漏掉它。

## 三、启用 GitHub Pages

1. 打开仓库的 **Settings**。
2. 左侧选择 **Pages**。
3. 在 **Build and deployment > Source** 中选择 **GitHub Actions**。
4. 不需要另选主题，也不要选择 `Deploy from a branch`。本模板会直接生成并部署 Pages artifact。

工作流部署 Pages 需要 `pages: write` 和 `id-token: write`。模板已经在工作流顶部声明；还声明了 `contents: write`，用于把最后一次成功抓取的 XML 保存回仓库。

## 四、首次手动运行

1. 打开仓库的 **Actions**。
2. 左侧选择 **Update and publish RSS**。
3. 点击右侧 **Run workflow**，分支选择 `main`，再次点击 **Run workflow**。
4. 等待 `build`、`deploy` 完成。
5. 打开 **Settings > Pages**，页面顶部会显示站点地址；也可以在工作流的 `deploy` 作业里查看 `page_url`。
6. 访问站点首页，例如：

   ```text
   https://你的用户名.github.io/rss-relay/
   ```

   首页会列出每个订阅地址、状态、条目数和错误摘要。

首次运行可能出现三种状态：

| 状态 | 含义 | 阅读器是否可用 |
|---|---|---|
| `正常` | 本次抓取、解析和输出都成功 | 可用 |
| `旧版` | 本次失败，继续发布此前成功版本 | 可用，但内容暂未更新 |
| `失败` | 本次失败，而且从未生成过旧版本 | 不可用，需要排查 |

如果任一源为“旧版”或“失败”，Pages 仍会部署，Actions 运行结果会标红用于提醒。这是有意设计的：一个坏源不会拖累其他源。

## 五、订阅

1. 从 Pages 首页复制完整 XML 地址，当前 SPJ 示例为：

   ```text
   https://你的用户名.github.io/rss-relay/feeds/spj-journalremotesensing.xml
   ```

2. 在浏览器无登录、无 Cookie 的隐私窗口中打开它，确认能看到 XML，而不是 GitHub 404 页面。
3. 新增 RSS 订阅，粘贴该 Pages 地址。
4. 手动触发订阅刷新。
5. 订阅成功后，后续只访问 Pages 地址，不再直接访问 `spj.science.org`。

Pages/CDN 可能有数分钟缓存，因此刚运行完 Actions 时不一定在每个地区立即看到新内容。

## 六、调整定时频率

工作流位于 `.github/workflows/update-rss.yml`，默认配置是：

```yaml
schedule:
  - cron: "17,47 * * * *"
```

即每小时第 17、47 分钟运行，两次间隔 30 分钟。故意避开整点，因为 GitHub 明确提示整点附近负载较高，计划任务可能延迟。

常用写法：

| 需求 | cron |
|---|---|
| 每 15 分钟 | `7,22,37,52 * * * *` |
| 每 30 分钟 | `17,47 * * * *` |
| 每小时 | `17 * * * *` |
| 每 6 小时 | `17 */6 * * *` |
| 每天 UTC 02:17 | `17 2 * * *` |

GitHub 计划任务的最短间隔是 5 分钟。默认按 UTC；当前 GitHub 也支持给 schedule 添加 IANA 时区，但 RSS 抓取一般不需要绑定本地时间。计划任务只在默认分支上运行，而且工作流文件必须存在于默认分支。公开仓库连续 60 天没有任何活动时，GitHub 会自动禁用计划任务，需要到 Actions 页面重新启用。

## 七、增加新的 RSS 源

只需要修改 `config/feeds.yml`，在 `feeds:` 下增加一段：

```yaml
- id: nature-news
  name: Nature News
  enabled: true
  url: https://example.org/feed.xml
  output: feeds/nature-news.xml
  mode: passthrough
```

保存并推送到 `main`。由于工作流监听 `config/**` 的变更，它会立即运行；无需等下一次 cron。成功后，新地址是：

```text
https://你的用户名.github.io/rss-relay/feeds/nature-news.xml
```

`id` 只能使用小写字母、数字、下划线和连字符，必须唯一。`output` 也必须唯一，建议固定写成 `feeds/<id>.xml`。

### 处理模式

| `mode` | 作用 | 适用情况 |
|---|---|---|
| `passthrough` | 校验后原样发布源站字节，字段保留最完整 | 原订阅本身合法，只是阅读器无法访问源站；优先使用 |
| `normalize` | 解析 RSS/Atom，再生成标准 RSS 2.0 | 阅读器能访问但解析失败、Atom 兼容性差、XML 有非关键格式差异 |

若 `passthrough` 在 Pages 上能打开但阅读器仍解析失败，把该源改为：

```yaml
mode: normalize
max_items: 100
```

规范化会尽量保留标题、链接、摘要、正文、GUID、日期、作者、分类和 enclosure，但某些厂商私有扩展字段可能丢失。因此不要一开始就对所有源使用 `normalize`。

### 针对反爬或特殊请求头

```yaml
- id: special-site
  name: Special Site
  enabled: true
  url: https://example.org/action/feed
  output: feeds/special-site.xml
  mode: passthrough
  warmup_url: https://example.org/
  warmup_delay: 1
  timeout: 45
  retries: 4
  headers:
    Accept: application/rss+xml, application/xml, text/xml
    Accept-Language: zh-CN,zh;q=0.9,en;q=0.8
    Referer: https://example.org/
```

`warmup_url` 会先访问普通页面，让同一个 Session 获取 Cookie，再请求 RSS。默认即使预热页面返回 403，也会继续请求 RSS；只有设置 `warmup_required: true` 才把预热失败视为失败。

### 带令牌或认证的源

不要把 Token、Cookie、用户名、密码写进 `feeds.yml`。配置中只写环境变量名：

```yaml
headers_from_env:
  Authorization: PRIVATE_FEED_AUTH
```

然后：

1. 在仓库 **Settings > Secrets and variables > Actions** 新建 secret，例如 `PRIVATE_FEED_AUTH`，值为 `Bearer xxxxx`。
2. 在工作流 `jobs.build` 下增加：

   ```yaml
   build:
     runs-on: ubuntu-latest
     env:
       PRIVATE_FEED_AUTH: ${{ secrets.PRIVATE_FEED_AUTH }}
   ```

注意：最终 RSS 文件会通过 Pages 公开。即使源站需要认证，也不要中转含私人或付费敏感内容的订阅。

## 八、配置字段

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `true` | 是否启用该源 |
| `url` | 必填 | 原始 RSS/Atom URL |
| `output` | 必填 | Pages 内的相对输出路径 |
| `mode` | `passthrough` | 原样输出或规范化 |
| `timeout` | `30` | 每次 HTTP 请求超时秒数 |
| `retries` | `3` | 连接、读取或可重试状态码的重试数 |
| `retry_backoff` | `1.5` | 重试退避系数 |
| `max_bytes` | `20971520` | 单个响应最大字节数，默认 20 MiB |
| `max_items` | `100` | 规范化模式最多保留的条目数 |
| `require_items` | `true` | 零条目是否视为异常，防止空响应覆盖正常旧版 |
| `failure_policy` | `keep_old` | 失败时保留仓库中的上次成功文件 |
| `headers` | 无 | 该源的普通请求头 |
| `headers_from_env` | 无 | 从 Actions secret 环境变量读取敏感请求头 |
| `warmup_url` | 无 | 抓取 RSS 前访问的同站页面 |
| `title_override` | 无 | 规范化模式覆盖频道标题 |
| `link_override` | 无 | 规范化模式覆盖频道主页链接 |

`defaults:` 中的值作用于所有源；单个源同名字段会覆盖默认值。

## 九、查看日志与排错

1. 进入仓库 **Actions > Update and publish RSS**。
2. 点开最近一次运行，再打开 `build`。
3. 展开 **Fetch and build feeds**。
4. 每个源会输出 `[UPDATED]`、`[STALE]` 或 `[FAILED]` 和原因。
5. 运行页面的 **Summary** 也有汇总表。

常见错误：

| 日志 | 原因 | 处理 |
|---|---|---|
| `403` / `429` | WAF、频率限制、GitHub 出口 IP 被拦 | 降低频率；添加合理请求头/预热；必要时换自托管 runner 或代理 |
| `returned HTML instead of a feed` | 返回登录页、验证码或挑战页 | 在日志/本地保存响应检查；普通头无效时不要反复暴力请求 |
| `contains zero items` | 源站临时返回空 Feed，或选择器/参数失效 | 浏览器检查原 URL；确认期刊代码、参数；旧版会被保留 |
| `XML root ... is not RSS, Atom, or RDF` | URL 返回 API JSON、HTML 或其他 XML | 找真正 Feed URL，或为该站编写自定义适配器 |
| Pages 404 | Pages 未选 GitHub Actions，或首次 deploy 失败 | 检查 Settings > Pages 和 `deploy` 日志 |
| `git push` 被拒绝 | 默认分支保护或 Actions 无写权限 | 给工作流 `contents: write`，检查组织策略；新建专用无保护仓库最省事 |

### 订阅源仍然失败怎么办

本方案改变的是“请求出口”和“对阅读器暴露的地址”，不保证绕过所有源站防护。如果订阅源同时屏蔽 GitHub 托管 runner，日志仍可能出现 403、HTML challenge 或空响应。按顺序处理：

1. 先保留模板中的 `warmup_url`、`Referer`、`Accept`，手动重跑一次；
2. 把频率降到每小时，避免触发频控；
3. 检查源是否存在更稳定的官方 Crossref、DOAJ 或期刊 API 替代；
4. 使用你自己的 VPS 作为 GitHub self-hosted runner，或改用 Cloudflare Worker/VPS 定时任务；
5. 如果必须执行 JavaScript/验证码，单纯 `requests` 方案不合适，也不建议用自动化方式规避站点访问控制。

## 十、为什么保存 XML 回仓库

每次成功生成后，工作流只提交 `public/feeds/` 下发生变化的 XML。`index.html` 和 `status.json` 不提交，只随当次 Pages artifact 发布。这样：

- 某源下一次失败时，有上一份成功 XML 可继续服务；
- 内容不变时不会产生无意义提交；
- 可以从 Git 历史查看 Feed 实际何时变化；
- Actions 用 `GITHUB_TOKEN` 推送的提交不会递归触发新的工作流。

如果你不想在 `main` 保存生成文件，可以进一步改为专用状态分支或对象存储；对少量期刊 RSS，中转文件直接保存在仓库最简单可靠。

## 十一、限制与建议

- GitHub schedule 不是精确计时器，可能延迟，极端高负载时还可能丢弃排队任务；RSS 通常不需要分钟级严格准时。
- GitHub Pages 是静态公开托管，不适合带用户身份的私密 Feed。
- 源站如果按 GitHub IP 封禁，修改浏览器头通常无效，需要换网络出口。
- 遵守源站条款、robots 政策、版权和合理抓取频率。期刊 eTOC 一般每 30～60 分钟抓取已足够。
- 新增很多源时仍可放在同一配置中；数量很大或单次执行接近 Actions 超时，再按分组拆成多个工作流。

## 官方参考

- GitHub Pages 发布源与自定义 Actions 工作流：https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
- Pages 自定义工作流及权限：https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
- `schedule` 触发器、cron、时区和限制：https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- 手动运行工作流：https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow