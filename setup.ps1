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

# ---------------------------------------------------------------- 下载（多镜像回退）
function Fetch($urls, $dest, $label) {
    foreach ($u in $urls) {
        $host_ = ([Uri]$u).Host
        try {
            Say "  试 $host_ ..." 'DarkGray'
            $sw = [Diagnostics.Stopwatch]::StartNew()
            $wc = New-Object Net.WebClient
            $wc.Headers.Add('User-Agent', 'Mozilla/5.0')
            $wc.DownloadFile($u, $dest)
            $sw.Stop()
            $mb = (Get-Item $dest).Length / 1MB
            Say ("  OK  {0}  {1:N1} MB  {2:N1}s" -f $host_, $mb, $sw.Elapsed.TotalSeconds) 'Green'
            return $true
        } catch {
            Say ("  失败 {0}: {1}" -f $host_, $_.Exception.Message) 'DarkYellow'
        }
    }
    return $false
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
$Wheels = @(
    'polars-2.0.0-py3-none-any.whl',
    'polars_runtime_32-2.0.0-cp310-abi3-win_amd64.whl',
    'awpy-3.1.1-cp312-cp312-win_amd64.whl',
    'rich-15.0.0-py3-none-any.whl',
    'typer-0.27.3-py3-none-any.whl',
    'pygments-2.21.0-py3-none-any.whl',
    'markdown_it_py-4.2.0-py3-none-any.whl',
    'mdurl-0.1.2-py3-none-any.whl',
    'annotated_doc-0.0.5-py3-none-any.whl',
    'shellingham-1.5.4-py2.py3-none-any.whl'
)

$SimpleMirrors = @(
    'https://pypi.tuna.tsinghua.edu.cn/simple',
    'https://mirrors.aliyun.com/pypi/simple',
    'https://mirrors.cloud.tencent.com/pypi/simple',
    'https://repo.huaweicloud.com/repository/pypi/simple',
    'https://pypi.org/simple'
)

# 在 simple 索引页里按**确切文件名**找下载链接；包名取文件名第一个 '-' 之前那段
function Pick-WheelUrl($whl, $mirror) {
    $pkg = ($whl -split '-')[0]
    try {
        $html = (New-Object Net.WebClient).DownloadString("$mirror/$pkg/")
    } catch {
        return $null
    }
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
    $i = 0
    foreach ($whl in $Wheels) {
        $i++
        Step "依赖 $i/$($Wheels.Count)：$whl"
        $done = $false
        foreach ($m in $SimpleMirrors) {
            $rel = Pick-WheelUrl $whl $m
            if (-not $rel) { continue }
            # href 是相对索引页的路径（形如 ../../packages/xx/yy/xxx.whl），补成绝对地址
            $pkg = ($whl -split '-')[0]
            $abs = ([Uri]::new([Uri]"$m/$pkg/", $rel)).AbsoluteUri
            $dest = Join-Path $TmpDir $whl
            Say ("  从 {0} 下载" -f ([Uri]$m).Host) 'DarkGray'
            if (Fetch @($abs) $dest $whl) {
                Expand-Archive -Path $dest -DestinationPath $Site -Force
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

Step '第 2 步 / 2：解析依赖（约 60 MB）'
$bad = Install-Wheels
if ($bad.Count -gt 0) {
    Say ''; Say ('!! 这些包没装上：' + ($bad -join '、')) 'Red'
    Say '   检查网络后重跑 SETUP.bat；已装上的会自动跳过。' 'Yellow'
    exit 1
}

# 自检：能 import awpy 才算真装好
Step '自检'
$py = Join-Path $PyDir 'python.exe'
$chk = & $py -c "import awpy, polars; print('ok', awpy.__version__ if hasattr(awpy,'__version__') else '')" 2>&1
if ($LASTEXITCODE -ne 0) {
    Say ('!! 装完了但 import awpy 失败：' + $chk) 'Red'
    exit 1
}
Say ('  import awpy 成功：' + $chk) 'Green'

Remove-Item $TmpDir -Recurse -Force -ErrorAction SilentlyContinue
Say ''
Say '环境就绪，可以双击 START.bat 启动了。' 'Green'
exit 0
