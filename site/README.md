# iMuninn 文档站

Astro Starlight。内容不在这里写：`npm run sync` 从 `../docs/` 和 `../protocol/` 生成 `src/content/docs/`（已 gitignore），`build` / `dev` 会先自动 sync。

- 栏目 = `docs/` 的一级目录（start / python / web / cpp / protocol / phone / dev / agents / design），页面标题取文件的一级标题，`NN-` 前缀决定顺序，slug 去掉前缀。
- 英文：`docs/en/<同名路径>`；没有英文版的页面回退到中文。
- 生成页（CLI / API / 协议消息）由 `tools/gen-docs.py` 写入 `docs/`，中英共用。
- 每页的 meta description（搜索结果和分享预览用）写在 `scripts/descriptions.mjs`，按 slug 分中英文。新增公开页面时顺手加一条；没写的页面用站点默认描述，也不会进 llms.txt。
- sync 同时生成 `public/llms.txt` 和 `public/llms-full.txt`（给 AI 爬虫和 agent），只包含 `descriptions.mjs` 里列出且本次构建存在的页面，所以私有栏目不会混进去。
- 404 页由 `sync` 写成 `src/content/docs/404.md`（中英双语，因为 Starlight 只生成一个 `dist/404.html`，Cloudflare Pages 对 `/en/` 下的缺页也返回它）。Web 查看器的 404 是 `host/web/public/404.html`（GitHub Pages 用）。
- 分享预览图是 `public/og.jpg`（1200×630，从宣传图裁出），在 `astro.config.mjs` 的 `head` 里引用。
- 首页右侧的 App 图是 `src/assets/home-app.webp`（1056×1212，透明底，只有三台手机、没有文字），在 `src/components/Hero.astro` 里和 App Store 徽章放在一起。它用无头 Chrome 从 `mobile/store-screenshots/artwork/art.html` 渲染：去掉左侧文案和背景渐变（`.copy` 隐藏、`body` 透明），用 6.3in 截图 01 / 05 / 02 作中 / 左 / 右，再用 sharp 转 WebP。

- iPhone 参数页（`/parameter-definition/`，英文 `/en/parameter-definition/`）不是文档页，是 `src/pages/` 下的独立页面：`src/components/ParameterDefinition.astro`（界面和中英文文案）加 `src/scripts/parameter-viewer.js`（three.js 3D）。数据只有一份，就是仓库里的 `protocol/frames/iphone-frames.json`，构建时由 `src/pages/parameter-definition/iphone-frames.json.js` 原样发布到 `/parameter-definition/iphone-frames.json`，页面再去取。顶栏的“iPhone 参数”入口在 `src/components/Header.astro`，在新标签页打开。尺寸旁的“自动识别 / 已人工核验”来自 `protocol/frames/review.json`，改法见 `protocol/frames/README.md`。
- 参数页的“下载 3D 模型”按钮指向 `public/parameter-definition/models/` 下已提交的静态文件（30 个机型的 URDF、MJCF、glb，加一个 `manifest.json`，共约 1.1 MB）。它们由 Python 包生成，网站构建时不跑 Python。机型数据变了要重新生成并提交，否则 `host/python/tests/test_models.py` 会失败：

  ```bash
  imuninn hardware export --all --format all -o site/public/parameter-definition/models
  ```

  需要 `pip install "imuninn[models]"`（glb 用 trimesh）。

```bash
cd site && npm install
npm run dev        # http://localhost:4321
npm run build      # 输出 dist/
```

## 部署到 Cloudflare Pages

1. Cloudflare Dashboard → Workers & Pages → Create → Pages → 连接 GitHub 仓库。
2. 构建设置：Framework preset **Astro**；Root directory `site`；Build command `npm run build`；Output directory `dist`。
3. 环境变量 `NODE_VERSION=22`。
4. 自定义域名：`imuninn.projects.weijinqi.com`（`astro.config.mjs` 里的 `site` 已设为此值）。

也可以本地 `npx wrangler pages deploy dist --project-name imuninn`。
