using System.Text;

namespace UniApkBuilder
{
    public static class EnvLoader
    {
        /// <summary>
        /// 加载 .env 文件到当前进程的环境变量。
        /// </summary>
        /// <param name="filePath">.env 文件路径</param>
        /// <param name="overwrite">是否覆盖已存在的环境变量，默认 false</param>
        public static void Load(string filePath, bool overwrite = false)
        {
            if (!File.Exists(filePath))
                return; // 文件不存在时静默忽略，也可以改为抛异常

            foreach (var rawLine in File.ReadLines(filePath))
            {
                if (TryParseLine(rawLine, out var key, out var value))
                {
                    if (overwrite || Environment.GetEnvironmentVariable(key) is null)
                    {
                        Environment.SetEnvironmentVariable(key, value);
                    }
                }
            }
        }

        private static bool TryParseLine(string rawLine, out string key, out string value)
        {
            key = string.Empty;
            value = string.Empty;

            var line = rawLine.Trim();
            if (line.Length == 0 || line[0] == '#')
                return false;

            // 支持 export KEY=VALUE
            if (line.StartsWith("export", StringComparison.Ordinal) &&
                line.Length > 6 && char.IsWhiteSpace(line[6]))
            {
                line = line.Substring(7).TrimStart();
            }

            int eq = line.IndexOf('=');
            if (eq <= 0)
                return false;

            key = line.Substring(0, eq).Trim();
            if (key.Length == 0)
                return false;

            value = ParseValue(line.Substring(eq + 1));
            return true;
        }

        private static string ParseValue(string rawValue)
        {
            // 跳过前导空白，但记录是否有前导空白
            int start = 0;
            while (start < rawValue.Length && char.IsWhiteSpace(rawValue[start]))
                start++;

            if (start >= rawValue.Length)
                return string.Empty;

            string value = rawValue.Substring(start);

            if (value[0] == '"')
                return ParseDoubleQuoted(value);

            if (value[0] == '\'')
                return ParseSingleQuoted(value);

            // 未引号值：如果等号后只有空白然后 #，视为空值/注释
            if (value[0] == '#' && start > 0)
                return string.Empty;

            return ParseUnquoted(value).TrimEnd();
        }

        private static string ParseDoubleQuoted(string value)
        {
            var sb = new StringBuilder(value.Length);
            for (int i = 1; i < value.Length; i++)
            {
                char c = value[i];
                if (c == '\\' && i + 1 < value.Length)
                {
                    char next = value[++i];
                    sb.Append(next switch
                    {
                        'n' => '\n',
                        'r' => '\r',
                        't' => '\t',
                        '\\' => '\\',
                        '"' => '"',
                        _ => next
                    });
                }
                else if (c == '"')
                {
                    break;
                }
                else
                {
                    sb.Append(c);
                }
            }
            return sb.ToString();
        }

        private static string ParseSingleQuoted(string value)
        {
            int end = value.IndexOf('\'', 1);
            return end >= 0 ? value.Substring(1, end - 1) : value.Substring(1);
        }

        private static string ParseUnquoted(string value)
        {
            // 行内注释：仅当 # 前有空白时截断
            for (int i = 0; i < value.Length; i++)
            {
                if (value[i] == '#' && i > 0 && char.IsWhiteSpace(value[i - 1]))
                {
                    return value.Substring(0, i).TrimEnd();
                }
            }
            return value;
        }
    }
}
