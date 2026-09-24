# 本地字体来源

`docs/fonts.css` 与此目录字体来自项目已有 `frontend/dist/assets/` 中的 Noto Sans SC 和 Exo 2，原前端依赖为 `@fontsource/noto-sans-sc` 与 `@fontsource/exo-2`。仅提取 400 / 700 字重的字体声明、Unicode 范围和 WOFF2 字体，不复制旧应用 JS、页面样式或业务配置；较小的内联字体也转为本地文件。

两份展示 HTML 使用相对路径访问这些字体，保留目录即可离线展示，不依赖前端构建哈希稳定或外部字体服务。其他字重由浏览器按可用字体合成，缺字回退本机字体。

`deploy/sync-doc-fonts.py` 可从含上述字体的新前端构建中重新生成此静态资产集合，不联网。该步骤不是业务前端构建，也不能作为新架构构建验证的替代。更新字体依赖时应一并核对上游许可证与分发要求；这两种字体采用 SIL Open Font License 1.1。
