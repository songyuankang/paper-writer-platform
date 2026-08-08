# 公网部署

这个项目由两部分组成：前端 React（`paper-writer-web`）和后端 FastAPI（`paper-writer-api`）。别人要能正常使用网页，前后端都必须跑起来；只托管前端静态文件是不够的。

## 方式一：一台云服务器 + Docker（推荐）

1. 购买一台云服务器（国内服务器绑域名需要 ICP 备案，境外或香港服务器通常不需要）。
2. 在服务器上安装 Docker 和 Docker Compose。
3. 克隆仓库并进入：

```bash
git clone https://github.com/songyuankang/paper-writer-platform.git
cd paper-writer-platform
```

4. 创建 `.env`，按需填写：

```dotenv
DEEPSEEK_API_KEY=你的key
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
WEB_PORT=80
VITE_API_URL=
```

5. 构建并启动：

```bash
docker compose up -d --build
```

6. 在云服务器安全组/防火墙开放 `WEB_PORT`（默认 80）。浏览器访问 `http://服务器公网IP` 即可。

`VITE_API_URL` 留空时，Nginx 会把 `/api` 自动转发到后端容器，浏览器端不需要处理跨域。有域名后，把域名解析到服务器 IP，再用 Caddy 或 Nginx + certbot 配置 HTTPS。

## 方式二：免费托管（前后端分开）

### 后端 Render

1. 在 render.com 用 GitHub 登录，新建 Web Service，选择 `paper-writer-platform` 仓库。
2. Root Directory 填 `paper-writer-api`，Environment 选 Docker。
3. 设置环境变量：`PAPER_WRITER_SCRIPTS_DIR=/app/paper_writer_scripts`、`DEEPSEEK_API_KEY` 等。
4. 部署完成后会得到一个 `https://xxx.onrender.com` 地址。

注意：Render 免费实例的磁盘不是持久的，重启后 `uploads`、`outputs`、数据库等会丢失，适合测试；正式使用建议用付费实例或把数据放到外部存储。

### 前端 Vercel

1. 在 vercel.com 用 GitHub 登录，导入 `paper-writer-platform`。
2. Root Directory 填 `paper-writer-web`。
3. Framework 选 Vite，Build Command 填 `npm run build`，Output Directory 填 `dist`。
4. 环境变量 `VITE_API_URL` 填后端地址，例如 `https://xxx.onrender.com`。
5. 部署完成后得到 `https://xxx.vercel.app`，即可公开访问。

仓库里已经包含 `vercel.json` 和 `public/_redirects`，Vercel / Netlify 的 SPA 路由会自动回退到 `index.html`。
