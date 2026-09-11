# uni-app Android 打包器

把 uni-app 项目打包为本地 Android APK。分两步：先部署打包服务，再在项目里运行客户端。

## Docker 部署

### 1. 准备离线 SDK

Android离线SDK下载地址：[Android 离线SDK | uni小程序SDK](https://nativesupport.dcloud.net.cn/AppDocs/download/android.html)

把 uni-app Android 离线打包 SDK 解压到 `uni-app-sdk/` 下，每个版本一个目录，目录名用版本号（如 `5.24`），内容保持 SDK 原样：

```
uni-app-sdk/5.24/HBuilder-Integrate-AS/
uni-app-sdk/5.24/SDK/
```

需要支持哪个版本，就放入哪个版本的目录。只放`HBuilder-Integrate-AS`和`SDK`文件夹就行。

### 2. docker compose

```yml
services:
  server:
    image: mghcool/uni-apk-builder:latest
    container_name: uni-apk-builder
    restart: unless-stopped
    volumes:
      - ./uni-app-sdk:/data/uni-app-sdk:ro
    ports:
      - "8020:80"
```

启动

```bash
docker compose up -d
```



