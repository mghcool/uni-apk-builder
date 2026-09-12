FROM ubuntu:24.04

LABEL maintainer="mghcool"

# --- 环境变量配置 ---
ENV ANDROID_SDK_TOOLS_VERSION="15859902"
ENV ANDROID_SDK_TOOLS_CHECKSUM="4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583"
ENV ANDROID_HOME="/opt/android-sdk"
ENV ANDROID_SDK_ROOT="$ANDROID_HOME"
ENV PATH="$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools"
ENV DEBIAN_FRONTEND=noninteractive
ENV LANG="en_US.UTF-8"
ENV TZ=Asia/Shanghai
ENV HOME="/root"

# --- 安装基础依赖 ---
RUN apt-get -qq update \
    && apt-get -qqy --no-install-recommends install \
    apt-utils \
    build-essential \
    openjdk-21-jdk \
    openjdk-21-jre-headless \
    software-properties-common \
    libssl-dev \
    libffi-dev \
    python3-dev \
    pkg-config \
    libstdc++6 \
    libpulse0 \
    libglu1-mesa \
    zip \
    unzip \
    curl \
    git \
    wget \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# --- 下载并解压 Android 命令行工具 ---
RUN curl -s https://dl.google.com/android/repository/commandlinetools-linux-${ANDROID_SDK_TOOLS_VERSION}_latest.zip > /tools.zip \
    && echo "${ANDROID_SDK_TOOLS_CHECKSUM}  /tools.zip" | sha256sum -c - \
    && mkdir -p $ANDROID_HOME/cmdline-tools \
    && unzip -qq /tools.zip -d $ANDROID_HOME/cmdline-tools \
    && mv $ANDROID_HOME/cmdline-tools/cmdline-tools $ANDROID_HOME/cmdline-tools/latest \
    && rm -v /tools.zip

# --- 接受许可并安装指定 SDK 组件 ---
RUN yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses --sdk_root=${ANDROID_SDK_ROOT} \
    && $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --sdk_root=${ANDROID_SDK_ROOT} \
    "platforms;android-35" \
    "platforms;android-36" \
    "build-tools;35.0.0" \
    "build-tools;36.0.0" \
    "platform-tools"

# --- 下载 Gradle 分发包，多个版本间用空格隔开 ---
ARG GRADLE_VERSIONS="8.11.1 8.14.3"
ENV GRADLE_DIST_DIR="/opt/gradle-dist"
RUN mkdir -p $GRADLE_DIST_DIR \
    && for v in $GRADLE_VERSIONS; do \
        curl -fsSL "https://mirrors.cloud.tencent.com/gradle/gradle-${v}-bin.zip" \
            -o "$GRADLE_DIST_DIR/gradle-${v}-bin.zip"; \
    done \
    && chmod 644 $GRADLE_DIST_DIR/*.zip


COPY UniApkBuilder/UniApkBuilder/bin/publish/UniApkBuilder.exe /data/server/wwwroot/

COPY server/ /data/server/
WORKDIR /data/server
EXPOSE 80
CMD ["python3", "/data/server/server.py"]
