using System.Diagnostics;
using System.IO.Compression;
using System.Net.Http.Headers;
using System.Net.ServerSentEvents;
using System.Reflection;
using System.Text;

namespace UniApkBuilder
{
    internal class Program
    {
        /// <summary>当前路径</summary>
        static string _currentPath = AppContext.BaseDirectory;

        static int Main(string[] args)
        {
            // 当使用vscode等终端调用时，可以加上这个参数不等待结束。
            bool shouldWait = !args.Contains("--no-wait");

            Version version = Assembly.GetExecutingAssembly().GetName().Version!;

            Console.WriteLine($"uni-app APK 打包工具，版本：v{version.ToString(3)}");

            ApkConfig config;
            try
            {
                config = LoadConfig();
            }
            catch (Exception ex)
            {
                ConsoleErrorWriteLine(ex.Message);
                WaitExit(shouldWait);
                return -1;
            }

            string KeystorePath = Path.Combine(_currentPath, config.KeystoreFile);
            if (!File.Exists(KeystorePath))
            {
                ConsoleErrorWriteLine($"未找到证书文件：{KeystorePath}");
                WaitExit(shouldWait);
                return -1;
            }

            string zipPath;
            string outputPath;
            if (IsCliProject())
            {
                Console.WriteLine("当前项目为 [CLI 工程]");
                bool ok = CliBuildResource();
                if (!ok)
                {
                    WaitExit(shouldWait);
                    return -2;
                }

                outputPath = Path.Combine(_currentPath, "dist", "apk");
                zipPath = Path.Combine(outputPath, "temp.zip");
                string appPath = Path.Combine(_currentPath, "dist", "build", "app");
                string iconPath = Path.Combine(_currentPath, "unpackage", "res", "icons");

                if (!Directory.Exists(iconPath))
                {
                    ConsoleErrorWriteLine("该项目未生成应用图标，请先到 HBuilder X 中生成");
                    WaitExit(shouldWait);
                    return -3;
                }
                if (!Directory.Exists(outputPath)) Directory.CreateDirectory(outputPath);
                if (File.Exists(zipPath)) File.Delete(zipPath);

                using var zip = ZipFile.Open(zipPath, ZipArchiveMode.Create);
                ZipAddFolder(zip, appPath, "app");
                ZipAddFolder(zip, iconPath, "icons");
                zip.CreateEntryFromFile(KeystorePath, "app.keystore", CompressionLevel.Optimal);
            }
            else
            {
                Console.WriteLine("当前项目为 [HBuilderX 工程]");
                Console.WriteLine("必须保证已经通过HBuilderX生成了离线打包资源，如果已经生成，按任意键继续，如果未生成，请退出程序！");
                Console.ReadKey(true);

                string packageDir = Path.Combine(_currentPath, "unpackage");
                outputPath = Path.Combine(packageDir, "apk");
                zipPath = Path.Combine(outputPath, "temp.zip");
                string iconPath = Path.Combine(packageDir, "res", "icons");
                string appPath = Path.Combine(packageDir, "dist", "build", "app-plus");

                if (!Directory.Exists(iconPath))
                {
                    ConsoleErrorWriteLine("该项目未生成应用图标，请先到 HBuilder X 中生成");
                    WaitExit(shouldWait);
                    return -3;
                }
                if (!Directory.Exists(appPath))
                {
                    ConsoleErrorWriteLine("该项目未生成离线打包资源，请先到 HBuilder X 中生成");
                    WaitExit(shouldWait);
                    return -4;
                }
                if (!Directory.Exists(outputPath)) Directory.CreateDirectory(outputPath);
                if (File.Exists(zipPath)) File.Delete(zipPath);

                using var zip = ZipFile.Open(zipPath, ZipArchiveMode.Create);
                ZipAddFolder(zip, appPath, "app");
                ZipAddFolder(zip, iconPath, "icons");
                zip.CreateEntryFromFile(KeystorePath, "app.keystore", CompressionLevel.Optimal);
            }

            RemoteBuild(config, zipPath, outputPath).GetAwaiter().GetResult();

            File.Delete(zipPath);

            WaitExit(shouldWait);
            return 0;
        }

        static void WaitExit(bool shouldWait)
        {
            if (shouldWait)
            {
                Console.Write("\n按任意键退出...");
                Console.ReadKey(true);
            }
        }

        static ApkConfig LoadConfig()
        {
            string envFile = ".env.apkconfig";
            string envPath = Path.Combine(_currentPath, envFile);
            if (!File.Exists(envPath)) throw new Exception($"未找到apk配置文件：{envFile}");

            EnvLoader.Load(envPath);
            string? hostUrl = Environment.GetEnvironmentVariable("UB_HOST_URL");
            if (string.IsNullOrWhiteSpace(hostUrl)) throw new Exception("未配置主机URL [UB_HOST_URL]");

            string? packageName = Environment.GetEnvironmentVariable("UB_PACKAGE_NAME");
            if (string.IsNullOrWhiteSpace(packageName)) throw new Exception("未配置APP包名 [UB_PACKAGE_NAME]");

            string? KeystoreName = Environment.GetEnvironmentVariable("UB_KEYSTORE_FILE");
            if (string.IsNullOrWhiteSpace(KeystoreName)) throw new Exception("未配置证书文件 [UB_KEYSTORE_FILE]");

            string? keystoreAlias = Environment.GetEnvironmentVariable("UB_KEYSTORE_ALIAS");
            if (string.IsNullOrWhiteSpace(keystoreAlias)) throw new Exception("未配置证书别名 [UB_KEYSTORE_ALIAS]");

            string? keystorePassword = Environment.GetEnvironmentVariable("UB_KEYSTORE_PASSWORD");
            if (string.IsNullOrWhiteSpace(keystorePassword)) throw new Exception("未配置证书密码 [UB_KEYSTORE_PASSWORD]");

            string? appKey = Environment.GetEnvironmentVariable("UB_DCLOUD_APPKEY");
            if (string.IsNullOrWhiteSpace(appKey)) throw new Exception("未配置离线Key [UB_DCLOUD_APPKEY]");

            return new ApkConfig()
            {
                HostUrl = hostUrl,
                PackageName = packageName,
                KeystoreFile = KeystoreName,
                KeystoreAlias = keystoreAlias,
                KeystorePassword = keystorePassword,
                DcloudAppKey = appKey
            };
        }

        static void ConsoleErrorWriteLine(string message)
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.Error.WriteLine(message);
            Console.ResetColor();
        }

        /// <summary>判断是否为cli项目</summary>
        /// <returns>是cli项目返回true</returns>
        static bool IsCliProject()
        {
            if (File.Exists(Path.Combine(_currentPath, "package.json")))
            {
                if (File.Exists(Path.Combine(_currentPath, "manifest.json")))
                {
                    return false; // package.json 和 manifest.json 在同一文件夹下视为非cli项目
                }
                return true;
            }
            return false;
        }

        /// <summary>cli项目编译资源</summary>
        /// <returns></returns>
        static bool CliBuildResource()
        {
            var psi = new ProcessStartInfo
            {
                FileName = "cmd",
                Arguments = "/c npx uni build -p app",
                WorkingDirectory = _currentPath,
                UseShellExecute = false,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            };
            using var proc = new Process { StartInfo = psi };


            proc.OutputDataReceived += (s, e) =>
            {
                if (e.Data != null)
                {
                    Console.WriteLine(e.Data);
                }
            };
            proc.ErrorDataReceived += (s, e) =>
            {
                if (e.Data != null)
                {
                    Console.Error.WriteLine(e.Data);
                }
            };

            proc.Start();

            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();

            proc.WaitForExit();

            return proc.ExitCode == 0;
        }

        /// <summary>把 sourceDir 下所有文件递归加入 zip，zip 内前缀为 entryPrefix</summary>
        static void ZipAddFolder(ZipArchive zip, string sourceDir, string entryPrefix)
        {
            foreach (var file in Directory.GetFiles(sourceDir, "*", SearchOption.AllDirectories))
            {
                // Path.GetRelativePath 在 Windows 上返回 '\' 分隔的相对路径，
                // 必须统一替换为 '/'（ZIP 规范要求的条目分隔符），
                // 否则解压端会得到文件名带 '\' 的扁平文件
                string relative = Path.GetRelativePath(sourceDir, file).Replace('\\', '/');
                string entryName = string.IsNullOrEmpty(entryPrefix)
                    ? relative
                    : $"{entryPrefix}/{relative}";

                zip.CreateEntryFromFile(file, entryName, CompressionLevel.Optimal);
            }
        }

        static async Task RemoteBuild(ApkConfig cfg, string filePath, string outputPath)
        {
            string baseUrl = cfg.HostUrl.TrimEnd('/');

            string query = string.Join("&",
                $"package={Uri.EscapeDataString(cfg.PackageName)}",
                $"ksPwd={Uri.EscapeDataString(cfg.KeystorePassword)}",
                $"ksAlias={Uri.EscapeDataString(cfg.KeystoreAlias)}",
                $"appkey={Uri.EscapeDataString(cfg.DcloudAppKey)}");

            string url = $"{baseUrl}/api/build?{query}";

            await using var fs = File.OpenRead(filePath);

            using var req = new HttpRequestMessage(HttpMethod.Post, url)
            {
                Content = new StreamContent(fs),
            };
            req.Content.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");

            using var http = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };

            // 关键：ResponseHeadersRead，否则 HttpClient 会把整个 SSE 流缓冲完才返回
            using var resp = await http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead);

            if (!resp.IsSuccessStatusCode)
            {
                // 400/500：服务端此时返回的是 JSON {"error": "..."}，还没进入 SSE 流
                var err = await resp.Content.ReadAsStringAsync();
                Console.WriteLine($"[HTTP {(int)resp.StatusCode}] {err}");
                return;
            }

            // ---- 2) 用 SseParser 逐条读取构建日志 ----
            await using var stream = await resp.Content.ReadAsStreamAsync();
            var parser = SseParser.Create(stream);
            var success = false;

            await foreach (var item in parser.EnumerateAsync())
            {
                var line = item.Data ?? string.Empty;
                if (line.Length == 0) continue;            // 服务端每 30 秒发一次心跳空行，跳过
                Console.WriteLine(line);                       // 打到控制台 / UI / 日志文件

                if (line.StartsWith("=== 构建结束"))
                {
                    success = line.Contains("exit=0");     // exit=1 表示构建失败
                    break;                                 // 收到结束标记立即退出，不依赖连接 EOF
                }
            }

            if (!success) return;

            // ---- 3) 下载最新 APK（从 Content-Disposition 读取服务端原始文件名）----
            Console.WriteLine("开始下载Apk...");
            await DownloadApkAsync(http, baseUrl, outputPath);
        }

        /// <summary>下载服务端最新 APK 到 outputPath，并实时输出下载进度</summary>
        /// <returns>下载并保存成功返回 true</returns>
        static async Task<bool> DownloadApkAsync(HttpClient http, string baseUrl, string outputPath)
        {
            // 必须用 ResponseHeadersRead：否则 HttpClient 会把整个 APK 缓冲完才返回，
            // 既拿不到流式进度，也会在内存里多占一份 APK 大小
            using var resp = await http.GetAsync($"{baseUrl}/api/download", HttpCompletionOption.ResponseHeadersRead);
            if (!resp.IsSuccessStatusCode)
            {
                Console.WriteLine($"[HTTP {(int)resp.StatusCode}] APK 下载失败");
                return false;
            }

            // 优先取 filename*（RFC 5987，支持中文），退回 filename，最后退回本地兜底名
            var disposition = resp.Content.Headers.ContentDisposition;
            var remoteName = disposition?.FileNameStar;
            if (string.IsNullOrWhiteSpace(remoteName))
                remoteName = disposition?.FileName;
            remoteName = Path.GetFileName(remoteName?.Trim('"') ?? string.Empty); // 只取文件名，防路径穿越
            if (string.IsNullOrWhiteSpace(remoteName))
                remoteName = $"app-{DateTime.Now:yyMMddHHmmss}.apk";

            string savePath = Path.Combine(outputPath, remoteName);

            long? total = resp.Content.Headers.ContentLength;   // 服务端未给长度时为 null
            long received = 0;
            long lastReportedBytes = 0;
            int lastPercent = -1;
            int lastLineLength = 0;

            // 控制台支持 \r：在同一行原地刷新进度；
            // 输出被重定向（写入日志文件 / UI 抓取）时 \r 无效，只能换行输出，否则日志里会堆满控制字符
            bool inPlace = !Console.IsOutputRedirected;

            void ReportProgress()
            {
                string text;
                if (total is > 0)
                {
                    int percent = (int)(received * 100 / total.Value);
                    if (percent == lastPercent) return;
                    lastPercent = percent;
                    text = $"下载中 {percent,3}% ({received / 1024.0 / 1024:F1}/{total.Value / 1024.0 / 1024:F1} MB)";
                }
                else
                {
                    if (received - lastReportedBytes < 1024 * 1024) return;   // 长度未知时每满 1MB 报一次
                    lastReportedBytes = received;
                    text = $"下载中 {received / 1024.0 / 1024:F1} MB";
                }

                if (!inPlace)
                {
                    Console.WriteLine(text);
                    return;
                }

                // PadRight 补齐上一次的宽度，防止新内容比旧内容短时残留尾巴
                Console.Write("\r" + text.PadRight(lastLineLength));
                lastLineLength = text.Length;
            }

            await using var source = await resp.Content.ReadAsStreamAsync();
            await using var target = File.Create(savePath);

            byte[] buffer = new byte[81920];
            int read;
            while ((read = await source.ReadAsync(buffer)) > 0)
            {
                await target.WriteAsync(buffer.AsMemory(0, read));
                received += read;
                ReportProgress();
            }

            if (inPlace) Console.WriteLine();   // 进度行收尾，别让最终信息拼在进度后面
            Console.WriteLine($"APK 已保存: {savePath}（{received / 1024.0 / 1024:F1} MB）");
            return true;
        }
    }
}
