namespace UniApkBuilder
{
    /// <summary>配置信息</summary>
    public class ApkConfig
    {
        /// <summary>主机url</summary>
        public string HostUrl { get; set; } = string.Empty;

        /// <summary>app包名</summary>
        public string PackageName { get; set; } = string.Empty;

        /// <summary>证书文件</summary>
        public string KeystoreFile { get; set; } = string.Empty;

        /// <summary>证书别名</summary>
        public string KeystoreAlias { get; set; } = string.Empty;

        /// <summary>证书密码</summary>
        public string KeystorePassword { get; set; } = string.Empty;

        /// <summary>App离线打包Key</summary>
        public string DcloudAppKey { get; set; } = string.Empty;
    }
}
