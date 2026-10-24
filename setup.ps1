# Cross-Section 首次运行环境准备（Windows PowerShell 5.1+）
#
# 作用：程序目录下还没有 python\python.exe 时，自动从国内镜像装一套运行环境。
#   1. Python 3.12 embeddable（约 11 MB）
#   2. awpy 及其依赖的 win_amd64 wheel（约 60 MB，解压进 site-packages）
#
# 不需要管理员权限、不写注册表、不碰系统 Python。全部落在程序目录里，
# 删掉整个文件夹就干净了。
#
# 用法：SETUP.bat 会调用它；START.bat 发现没有运行环境时也会自动调。

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$PyDir  = Join-Path $Root 'python'
$Site   = Join-Path $PyDir 'Lib\site-packages'
$TmpDir = Join-Path $env:TEMP ('cs2tool_setup_' + [Guid]::NewGuid().ToString('N').Substring(0, 8))

function Say($msg, $color = 'Gray') { Write-Host $msg -ForegroundColor $color }
function Step($msg) { Write-Host ''; Write-Host "== $msg" -ForegroundColor Cyan }

# ---------------------------------------------------------------- 下载（多镜像 · 双方法回退）
$UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36'

# 先 WebClient（速度快，DLL 体量大也能扛），再 Invoke-WebRequest（UA 更可控）
function Try-Download($u, $dest) {
    if (Test-Path $dest) { Remove-Item $dest -Force -ErrorAction SilentlyContinue }
    try {
        $wc = New-Object System.Net.WebClient
        $wc.Headers['User-Agent'] = $UA
        $wc.DownloadFile($u, $dest)
        if ((Test-Path $dest) -and (Get-Item $dest).Length -gt 0) { return 'WebClient' }
    } catch {
        $script:lastErr = $_.Exception.Message
    }
    try {
        Invoke-WebRequest -Uri $u -OutFile $dest -UseBasicParsing -TimeoutSec 600 -UserAgent $UA
        if ((Test-Path $dest) -and (Get-Item $dest).Length -gt 0) { return 'Invoke-WebRequest' }
    } catch {
        $script:lastErr = $_.Exception.Message
    }
    return $null
}

function Fetch($urls, $dest, $label) {
    foreach ($u in $urls) {
        $host_ = ([Uri]$u).Host
        Say "  试 $host_ ..." 'DarkGray'
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $how = Try-Download $u $dest
        $sw.Stop()
        if ($how) {
            $mb = (Get-Item $dest).Length / 1MB
            Say ("  OK  {0}  {1:N1} MB  {2:N1}s  ({3})" -f $host_, $mb, $sw.Elapsed.TotalSeconds, $how) 'Green'
            return $true
        }
        $reason = if ($script:lastErr) { $script:lastErr } else { '未知原因' }
        Say ("  失败 {0}: {1}" -f $host_, $reason) 'DarkYellow'
    }
    return $false
}

# Expand-Archive 只认 .zip 扩展名，wheel 本质是 zip 但会被扩展名挡住 → 先改名再解
function Expand-Wheel($whlPath, $destDir) {
    $tmpZip = $whlPath + '.zip'
    Copy-Item -LiteralPath $whlPath -Destination $tmpZip -Force
    try {
        Expand-Archive -Path $tmpZip -DestinationPath $destDir -Force
    } finally {
        Remove-Item -LiteralPath $tmpZip -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------- 1. Python embeddable
$PyVersions = @('3.12.10', '3.12.9', '3.12.8')
$PyTemplates = @(
    'https://mirrors.huaweicloud.com/python/{0}/python-{0}-embed-amd64.zip',
    'https://registry.npmmirror.com/-/binary/python/{0}/python-{0}-embed-amd64.zip',
    'https://mirrors.aliyun.com/python-release/windows/python-{0}-embed-amd64.zip',
    'https://www.python.org/ftp/python/{0}/python-{0}-embed-amd64.zip'
)

function Install-Python {
    New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null
    $zip = Join-Path $TmpDir 'python-embed.zip'
    foreach ($v in $PyVersions) {
        $urls = $PyTemplates | ForEach-Object { $_ -f $v }
        Say "Python $v" 'White'
        if (Fetch $urls $zip "python $v") {
            Say "  解压到 python\ ..." 'DarkGray'
            if (Test-Path $PyDir) { Remove-Item $PyDir -Recurse -Force }
            Expand-Archive -Path $zip -DestinationPath $PyDir -Force
            # embeddable 默认关掉了 site-packages，必须显式写进 ._pth
            $pth = Join-Path $PyDir 'python312._pth'
            @('python312.zip', '.', 'Lib\site-packages', 'import site') |
                Set-Content -Path $pth -Encoding ASCII
            Say '  Python 就位' 'Green'
            return $true
        }
    }
    return $false
}

# ---------------------------------------------------------------- 2. 依赖 wheel
# 精确文件名，与 awpy 3.1.1 的实际依赖树一致。
# 不用「包名 + 版本号」去猜，是因为 PyPI 文件名会把连字符换成下划线
# （polars-runtime-32 → polars_runtime_32），且空版本会抓到最老的一版。
#
# 每个 wheel 配一个「装好后可 import 的模块名」，用于重跑时跳过已装的包
# （装机几十秒，不该每次都重下）。空字符串表示没有对应模块名，按同组判断。
$Wheels = [ordered]@{
    'polars-2.0.0-py3-none-any.whl'                    = 'polars'
    'polars_runtime_32-2.0.0-cp310-abi3-win_amd64.whl' = '_polars_runtime_32'
    'awpy-3.1.1-cp312-cp312-win_amd64.whl'             = 'awpy'
    'rich-15.0.0-py3-none-any.whl'                     = 'rich'
    'typer-0.27.3-py3-none-any.whl'                    = 'typer'
    'pygments-2.21.0-py3-none-any.whl'                 = 'pygments'
    'markdown_it_py-4.2.0-py3-none-any.whl'            = 'markdown_it'
    'mdurl-0.1.2-py3-none-any.whl'                     = 'mdurl'
    'annotated_doc-0.0.5-py3-none-any.whl'             = 'annotated_doc'
    'shellingham-1.5.4-py2.py3-none-any.whl'           = 'shellingham'
    # 回放页（rounddata）与局内事件解析（awpy_ingest）都直接 import demoparser2，
    # 它不在 awpy 的元数据依赖里，必须显式装，连它的四个依赖一起。
    'demoparser2-0.42.0-cp312-cp312-win_amd64.whl'     = 'demoparser2'
    'pandas-3.1.0-cp312-cp312-win_amd64.whl'           = 'pandas'
    'numpy-2.5.4-cp312-cp312-win_amd64.whl'            = 'numpy'
    'pyarrow-26.0.0-cp312-cp312-win_amd64.whl'         = 'pyarrow'
    'tqdm-4.70.1-py3-none-any.whl'                     = 'tqdm'
    # pandas 自己的必需依赖：少 dateutil 会直接 ImportError，少 tzdata 在 Windows 上
    # 时区相关操作会炸。这两条连同 six 一起，之前都漏了。
    'python_dateutil-2.9.0.post0-py2.py3-none-any.whl' = 'dateutil'
    'six-1.17.0-py2.py3-none-any.whl'                  = 'six'
    'tzdata-2026.5-py2.py3-none-any.whl'               = 'tzdata'
}

# 顺序按实测带宽排（2026-10 在本机测 pandas 前 3 MB）：
#   腾讯 27 MB/s · 华为 15 MB/s · 阿里 0.33 MB/s · 官方 0.02 MB/s · 清华（部分网络 404）
# 阿里排在前面时，120 MB 的装配要拖好几分钟；换腾讯/华为打头通常十几秒。
$SimpleMirrors = @(
    'https://mirrors.cloud.tencent.com/pypi/simple',
    'https://repo.huaweicloud.com/repository/pypi/simple',
    'https://pypi.tuna.tsinghua.edu.cn/simple',
    'https://mirrors.aliyun.com/pypi/simple',
    'https://pypi.org/simple'
)

# 在 simple 索引页里按**确切文件名**找下载链接；包名取文件名第一个 '-' 之前那段
function Pick-WheelUrl($whl, $mirror) {
    $pkg = ($whl -split '-')[0] -replace '_', '-'   # PyPI 规范名用连字符（python_dateutil → python-dateutil）
    $url = "$mirror/$pkg/"
    $html = $null
    # 索引页也用双方法：部分镜像对 WebClient 的默认 UA 直接 403
    try {
        $html = (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 120 -UserAgent $UA).Content
    } catch {
        try {
            $wc = New-Object System.Net.WebClient
            $wc.Headers['User-Agent'] = $UA
            $html = $wc.DownloadString($url)
        } catch {
            return $null
        }
    }
    if (-not $html) { return $null }
    # href 形如 ../../packages/xx/yy/awpy-3.1.1-cp312-cp312-win_amd64.whl#sha256=...
    # 捕获组只吃到 .whl 为止（[^"#]* 不含 #），后面可能还有 #sha256 片段
    $pattern = 'href="([^"#]*' + [Regex]::Escape($whl) + ')'
    $m = [Regex]::Match($html, $pattern)
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

function Install-Wheels {
    New-Item -ItemType Directory -Force -Path $Site | Out-Null
    $failed = @()
    # 一次性问 python 已经装好了哪些包（一个包开一次 python 太慢）。
    # find_spec 查可 import 的模块；_polars_runtime_32 这类没有模块名的，看目录。
    $pyExe = Join-Path $PyDir 'python.exe'
    $have = @()
    if (Test-Path $pyExe) {
        $mods = (($Wheels.Values | Where-Object { $_ }) -join ',')
        # 这段 python 代码里**不能出现双引号**：PowerShell 5.1 把含 " 的字符串
        # 当参数传给原生 exe 时转义不可靠，python 会收到破碎的代码（File "<string>", line 1）。
        # 所以路径用 os.path.join + 单引号，模块列表也用单引号包。
        $probe = 'import importlib.util as u,os,sys;site=os.path.join(sys.prefix,''Lib'',''site-packages'');' +
                 'mods=''' + $mods + '''.split('','');' +
                 'print('' ''.join(m for m in mods if u.find_spec(m) or os.path.isdir(os.path.join(site,m))))'
        $out = & $pyExe -c $probe 2>$null
        if ($out) { $have = @($out -split '\s+' | Where-Object { $_ }) }
    }
    $i = 0
    $total = $Wheels.Count
    foreach ($whl in $Wheels.Keys) {
        $i++
        $mod = $Wheels[$whl]
        if ($mod -and ($have -contains $mod)) {
            Say ("  [{0}/{1}] 跳过 {2}（已装）" -f $i, $total, $whl) 'DarkGray'
            continue
        }
        Step "依赖 $i/$total：$whl"
        $done = $false
        foreach ($m in $SimpleMirrors) {
            $rel = Pick-WheelUrl $whl $m
            if (-not $rel) { continue }
            # href 是相对索引页的路径（形如 ../../packages/xx/yy/xxx.whl），补成绝对地址
            $pkg = ($whl -split '-')[0] -replace '_', '-'   # PyPI 规范名用连字符（python_dateutil → python-dateutil）
            $abs = ([Uri]::new([Uri]"$m/$pkg/", $rel)).AbsoluteUri
            $dest = Join-Path $TmpDir $whl
            Say (("  从 {0} 下载" -f ([Uri]$m).Host)) 'DarkGray'
            if (Fetch @($abs) $dest $whl) {
                Expand-Wheel $dest $Site
                Say '  已解压到 site-packages' 'Green'
                $done = $true
                break
            }
        }
        if (-not $done) { $failed += $whl }
    }
    return $failed
}

# ---------------------------------------------------------------- 主流程
Say '=====================================================' 'White'
Say ' Cross-Section 首次运行：准备 Python 运行环境' 'White'
Say ' （只在第一次需要，之后不会重复）' 'DarkGray'
Say '=====================================================' 'White'

Step '第 1 步 / 2：Python 3.12 运行时'
if (-not (Install-Python)) {
    Say ''; Say '!! Python 下载失败：所有镜像都没连上。' 'Red'
    Say '   请检查网络后重试，或手动从 https://mirrors.huaweicloud.com/python/ 下载' 'Yellow'
    Say '   python-3.12.10-embed-amd64.zip 解压到程序目录的 python\ 里。' 'Yellow'
    exit 1
}

Step '第 2 步 / 2：解析依赖（约 120 MB）'
$bad = Install-Wheels
if ($bad.Count -gt 0) {
    Say ''; Say ('!! 这些包没装上：' + ($bad -join '、')) 'Red'
    Say '   检查网络后重跑 SETUP.bat；已装上的会自动跳过。' 'Yellow'
    exit 1
}

# 自检：能 import 解析链才算真装好（demoparser2 是回放页必需的，漏了就一起报出来）
Step '自检'
$py = Join-Path $PyDir 'python.exe'
$chk = & $py -c "import awpy, polars, demoparser2, pandas; print('ok', awpy.__version__ if hasattr(awpy,'__version__') else '')" 2>&1
if ($LASTEXITCODE -ne 0) {
    Say ('!! 装完了但 import 失败：' + $chk) 'Red'
    exit 1
}
Say ('  import awpy / polars / demoparser2 / pandas 成功：' + $chk) 'Green'

Remove-Item $TmpDir -Recurse -Force -ErrorAction SilentlyContinue
Say ''
Say '环境就绪，可以双击 START.bat 启动了。' 'Green'
exit 0
