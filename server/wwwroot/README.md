<div class="home-hero">

  # 📱 uni-app Android 打包

  <p class="desc">基于离线 SDK 的自动打包服务 —— 一键将 uni-app 项目打包为 Android APK</p>

</div>

<div class="home-cards">

  <a class="home-card" href="#/guide">
    <div class="icon">🚀</div>
    <h3>快速上手</h3>
    <p>从配置 `.env.apkconfig` 到生成 APK 的完整流程说明。</p>
  </a>

  <a class="home-card" href="#/guide?id=配置文件">
    <div class="icon">⚙️</div>
    <h3>配置文件</h3>
    <p>包名、证书、离线 Key 等配置项的获取与填写方法。</p>
  </a>

  <a class="home-card" href="#/guide?id=项目打包">
    <div class="icon">📦</div>
    <h3>项目打包</h3>
    <p>HBuilder X 可视化项目与 Cli 项目两种打包方式。</p>
  </a>

  <a class="home-card" href="#/guide?id=生成应用图标">
    <div class="icon">🖼️</div>
    <h3>应用图标</h3>
    <p>打包前如何使用 HBuilder X 生成应用图标文件。</p>
  </a>

</div>

## 使用流程概览

```mermaid
flowchart LR
  A[云打包一次<br>获取配置信息] --> B[创建 .env.apkconfig]
  B --> C[生成应用图标]
  C --> D[下载 UniApkBuilder.exe]
  D --> E{项目类型}
  E -->|可视化项目| F[HBuilder X 生成离线资源]
  E -->|Cli 项目| G[直接运行]
  F --> H[获得 APK]
  G --> H
```

> 💡 提示:首次使用前,**必须先进行一次云打包**,这样才有配置文件所需的信息。云端打包所使用的包名就是 APK 的包名,需慎重填写。