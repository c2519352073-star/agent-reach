# 视频/播客

YouTube、B站、小宇宙播客的字幕和转录。

> 本机默认把视频、音频、字幕、评论和转录文件保存到
> `E:\agent-reach\技能下载文件`（Git Bash：`/e/agent-reach/技能下载文件`）。
> 下面的命令统一使用 `DOWNLOAD_DIR`；如需覆盖，设置
> `AGENT_REACH_DOWNLOAD_DIR`。

```bash
DOWNLOAD_DIR="${AGENT_REACH_DOWNLOAD_DIR:-/e/agent-reach/技能下载文件}"
YTDLP_CACHE="$DOWNLOAD_DIR/.cache/yt-dlp"
mkdir -p "$DOWNLOAD_DIR" "$YTDLP_CACHE"
```

## YouTube (yt-dlp)

### 获取视频元数据

```bash
yt-dlp --dump-json "URL"
```

> 本机应使用 `yt-dlp 2026.10.21+`，并在
> `%APPDATA%\yt-dlp\config` 中配置 `--js-runtimes node`。

### 下载字幕

```bash
# 下载字幕 (不下载视频)
yt-dlp --cache-dir "$YTDLP_CACHE" --write-sub --write-auto-sub --sub-lang "zh-Hans,zh,en" --skip-download -o "$DOWNLOAD_DIR/%(id)s" "URL"

# 然后读取 .vtt 文件
cat "$DOWNLOAD_DIR"/VIDEO_ID.*.vtt
```

### 浏览器登录态兜底（仅在用户明确同意时）

遇到 `Sign in to confirm you're not a bot` 时，可临时读取 Chrome 登录态。不要导出或持久化 Cookie。

```bash
yt-dlp --cookies-from-browser "chrome:<PROFILE>" \
  --cache-dir "$YTDLP_CACHE" \
  --js-runtimes node \
  --ignore-no-formats-error \
  --extractor-args "youtube:player-client=web_embedded" \
  --write-subs --write-auto-subs \
  --sub-langs "en,zh-Hans" \
  --skip-download -o "$DOWNLOAD_DIR/%(id)s.%(ext)s" "URL"
```

> 2026-10-22 实测：`web_embedded` 能返回字幕；部分 IP 只开放 storyboard 格式，因此需要 `--ignore-no-formats-error`。
> 若报 `Could not copy Chrome cookie database`，改用实际登录 YouTube 的 `chrome:<PROFILE>`；仍失败再征得用户同意后关闭 Chrome 重试。

> `--ignore-no-formats-error` 只用于元数据/字幕路径，不代表视频可下载。
> 若 `--list-formats` 只返回 `sb0-sb3` storyboard，必须明确报告“仅字幕/元数据可用”。

### PO Token（视频格式受限时）

已安装 `bgutil-ytdlp-pot-provider 2.0.2`，默认脚本目录：

```text
%USERPROFILE%\bgutil-ytdlp-pot-provider\server
```

验证 provider 是否加载及是否生成 token：

```bash
yt-dlp -v --extractor-args "youtube:player-client=mweb" \
  --list-formats "URL"
```

日志应包含：

```text
PO Token Providers: bgutil:http-2.0.2, bgutil:script-node-2.0.2
Generating a gvs PO Token for mweb client via bgutil script
```

PO Token 不保证绕过机器人验证。若仍只有 storyboard，应换网络出口/住宅代理，
或降级为字幕和元数据模式。不要高频复用 YouTube 账号 Cookie，账号可能被标记。

### 完整视频下载（本机实测 2026-10-22）

当前网络出现 `429`、机器人验证或仅有 storyboard 时，以下组合已实测可以
下载并合并完整视频。前置条件：

1. Chrome 的 `Profile 2` 已登录 YouTube。
2. 默认使用 `Profile 2`，日常运行中的 `Profile 1` 不会锁住它的 Cookies 数据库。
3. `node`、`ffmpeg`、`yt-dlp 2026.10.21+`、`bgutil-ytdlp-pot-provider 2.0.2` 可用。

推荐使用稳定封装入口：

```bash
agent-reach youtube-download "URL" --quality 720

# 可选：显式指定其他 Chrome Profile
agent-reach youtube-download "URL" --quality 720 \
  --cookies-from-browser "chrome:Profile 1"

# 只解析格式，不下载
agent-reach youtube-download "URL" --simulate
```

封装会自动使用 E 盘输出和 yt-dlp 缓存、Cookie、EJS solver、PO Token，
并在 Chrome Cookie 数据库被锁时提前给出明确错误。

底层等价命令：

```bash
OUT="$DOWNLOAD_DIR/%(id)s.%(ext)s"
yt-dlp --newline --progress --no-playlist \
  --cache-dir "$YTDLP_CACHE" \
  --format "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]" \
  --merge-output-format mp4 \
  --cookies-from-browser "chrome:Profile 2" \
  --remote-components "ejs:github" \
  --extractor-args "youtube:player-client=mweb" \
  -o "$OUT" "URL"
```

> `ejs:github` 会下载并运行 yt-dlp 官方的 EJS challenge solver。只在用户明确
> 同意处理 YouTube 风控时使用，不要把它静默加入全局默认配置。
>
> `429` 警告本身不代表下载失败；若提供有效的浏览器 Cookie、PO Token 和 EJS
> solver，`yt-dlp` 仍可能继续完成下载。Cookie 只通过 `--cookies-from-browser`
> 临时读取，不导出、不持久化。

下载后校验完整时长并解码尾部 10 秒：

```bash
FILE="$DOWNLOAD_DIR/VIDEO_ID.mp4"
ffprobe -v error -show_entries format=duration,size -of json "$FILE"
ffmpeg -v error -sseof -10 -i "$FILE" -map 0:v:0 -map 0:a:0 -f null -
```

本机验证样本 `ErTFoK1wr84`：选择 `398+140`（AV1 720p + AAC），完整文件
`204,364,613` 字节、`4890.819s`（81 分 30.8 秒），尾部解码退出码 `0`。

### 获取评论

```bash
# 提取评论（best-effort，不保证完整）
yt-dlp --write-comments --skip-download --write-info-json \
  --cache-dir "$YTDLP_CACHE" \
  --extractor-args "youtube:max_comments=20" \
  -o "$DOWNLOAD_DIR/%(id)s" "URL"
# 评论在 .info.json 的 comments 字段中
```

### 搜索视频

```bash
yt-dlp --dump-json "ytsearch5:query"
```

> **字幕注意**: 手动上传的字幕提取可靠；自动生成字幕可能存在行间重复，需后处理。
> **评论注意**: `--write-comments` 基于网页抓取（非 YouTube Data API），部分评论可能丢失。

### 无字幕兜底：Whisper 音频转写

```bash
# 视频没有字幕时的兜底：下载音频并用 Whisper 转写（Groq 免费 key 即可）
agent-reach transcribe "https://www.youtube.com/watch?v=VIDEO_ID"
agent-reach transcribe ./local_audio.mp3 -o "$DOWNLOAD_DIR/transcript.txt"
```

> 需要先配置 key：`agent-reach configure groq-key gsk_xxx`（免费，console.groq.com）
> 或 `agent-reach configure openai-key sk-xxx`。默认 auto 模式：groq 失败自动降级 openai。

## B站 / Bilibili（bili-cli 为主，OpenCLI 补字幕）

> ⚠️ **不要用 yt-dlp 读 B站**：B站风控已全面 412 拦截 yt-dlp（实测最新版、直连/代理/带 Cookie 全部无效）。yt-dlp 只用于 YouTube。

### 视频详情/搜索/热门/排行 (bili-cli，只读无需登录)

```bash
# 视频详情（标题/UP主/时长/播放互动数据/字幕可用性）
agent-reach bili video BVxxx

# 搜索视频
agent-reach bili search "query" --type video -n 5

# 热门视频 / 排行榜
agent-reach bili hot -n 10
agent-reach bili rank -n 10

# 下载音频并切分为 ASR-ready WAV（无字幕时配合 agent-reach transcribe 转写）
agent-reach bili audio BVxxx -o "$DOWNLOAD_DIR"
```

> `agent-reach bili` 会强制 UTF-8 子进程环境，避免 Windows 下中文输出乱码。

### 字幕 (OpenCLI，需要桌面 Chrome)

```bash
# 先确认 B站登录态；字幕接口对多数视频要求 SESSDATA
opencli auth status --site bilibili --full -f json

# 字幕逐句带时间轴
opencli bilibili subtitle BVxxx

# OpenCLI 也能搜索/读视频元数据（备选）
opencli bilibili search "query" -f yaml
opencli bilibili video BVxxx -f yaml
```

> 退出码 `77` / `AUTH_REQUIRED` 表示该视频字幕需要登录，不是解析器故障。
> 在 OpenCLI 使用的 Chrome Profile 中登录 `bilibili.com` 后重试。

### 零配置兜底：搜索 API 直连

```bash
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
COOKIE_JAR="$DOWNLOAD_DIR/.tmp/bili_ck.txt"
mkdir -p "$(dirname "$COOKIE_JAR")"
curl -s -c "$COOKIE_JAR" -o /dev/null -A "$UA" "https://www.bilibili.com/"
curl -s -b "$COOKIE_JAR" -A "$UA" -e "https://www.bilibili.com/" \
  "https://api.bilibili.com/x/web-interface/search/all/v2?keyword=QUERY&page=1"
```

> **安装 bili-cli**: `pipx install bilibili-cli`（上游 2026-03 起停更但实测健康；只读场景无需登录，`bili login` 扫码可解锁动态/收藏等个人功能）。

## 小宇宙播客 / Xiaoyuzhou Podcast

### 转录单集播客（可选 --polish 增强标点）

```bash
# 输出 Markdown 到 E 盘。--polish 让 Llama 3.3 70B 给文稿补中文标点+合理分段
~/.agent-reach/tools/xiaoyuzhou/transcribe.sh --polish "https://www.xiaoyuzhoufm.com/episode/EPISODE_ID"
```

> 转写 prompt 已要求 Whisper 输出中文标点；若标点效果仍不理想，可加 `--polish` 用 Groq 上免费的 Llama 3.3 70B 补标点+合理分段（9 分钟播客约多 ~7 秒）。每次转写多一轮 LLM 调用，按需使用。

### 前置要求

1. **ffmpeg**: `brew install ffmpeg`
2. **Groq API Key** (免费): https://console.groq.com/keys
3. **配置 Key**: `agent-reach configure groq-key YOUR_KEY`
4. **首次运行**: `agent-reach install --env=auto` 安装工具

### 检查状态

```bash
agent-reach doctor
```

> 输出 Markdown 文件默认保存到 `E:\agent-reach\技能下载文件`；可用
> `AGENT_REACH_DOWNLOAD_DIR` 覆盖。

## 选择指南

| 场景 | 推荐工具 |
|-----|---------|
| YouTube 字幕 | yt-dlp |
| B站视频详情/搜索 | bili-cli |
| B站字幕 | opencli bilibili subtitle |
| 播客转录 | 小宇宙 transcribe.sh |
| 无字幕音视频 | agent-reach transcribe（B站音频先 `agent-reach bili audio`） |
