# mc-pc: Mission Control's PC helper (Windows PowerShell 5.1).
#  - every 5 s : asks mc-pi for commands (sleep) and for Filip's answers and ideas; writes them into D:\ai-hub
#  - every 15 s: sends a report: hub status-log tails, HANDOFF summary, pending approvals (+ pictures), parked AIs
#  - every ~5 s while the phone shows the Local AI card (or a PC mode switch runs): Local AI snapshot (mc_localai.py)
#  - every 10 min: usage numbers for Claude, Codex, Gemini, Antigravity
# Logins of Codex and Antigravity are read where their CLIs keep them, used in memory for one read-only
# usage call, and never sent or saved. Only numbers leave the PC.
# Config: mc-pc.json next to this file (git-ignored). Started by Task Scheduler (install-mc-pc.ps1).
param([switch]$Test, [switch]$TestRestart, [switch]$TestBitwarden, [switch]$TestLocalAi)   # -Test: print usage + report parts once and exit (nothing is sent)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $here 'mc-pc.log'
$Hub = 'D:\ai-hub'
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Write-Log($msg) {
    # Never throws: a failed log write must not end the helper (it runs inside the error handlers too).
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    for ($i = 0; $i -lt 3; $i++) {   # another program reading the log can block a write for a moment
        try { Add-Content -LiteralPath $log -Value $line -Encoding UTF8; break } catch { Start-Sleep -Milliseconds 300 }
    }
    try {
        if ((Get-Item -LiteralPath $log).Length -gt 512KB) {
            Get-Content -LiteralPath $log -Tail 500 | Set-Content -LiteralPath $log -Encoding UTF8
        }
    } catch { }
}


$cfg = Get-Content -LiteralPath (Join-Path $here 'mc-pc.json') -Raw | ConvertFrom-Json
$base = $cfg.url.TrimEnd('/')
$headers = @{ Authorization = "Bearer $($cfg.token)" }
Add-Type -AssemblyName System.Drawing

function Api($method, $path, $body = $null, $contentType = 'application/json; charset=utf-8') {
    $p = @{ Uri = "$base$path"; Method = $method; Headers = $headers; TimeoutSec = 15 }
    if ($null -ne $body) {
        $p.ContentType = $contentType
        [byte[]]$bytes = if ($body -is [byte[]]) { $body } else { $utf8.GetBytes((ConvertTo-Json $body -Depth 8 -Compress)) }
        $p.Body = $bytes   # typed: PowerShell 5.1 would otherwise send the bytes as a list of numbers
    }
    # Invoke-RestMethod in Windows PowerShell 5.1 reads a JSON reply without a charset as Latin-1 (Czech text came out garbled):
    # fetch the bytes and decode them as UTF-8 here.
    $r = Invoke-WebRequest @p -UseBasicParsing
    $text = $utf8.GetString($r.RawContentStream.ToArray())
    if ($text.Trim()) { $text | ConvertFrom-Json }
}

function Unix($dt) { [DateTimeOffset]::new($dt).ToUnixTimeSeconds() }
function ReadJson($path) { if (Test-Path -LiteralPath $path) { Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json } }

function Get-ClaudeAppProcesses { @(Get-Process Claude -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*\WindowsApps\Claude_*\app\Claude.exe' }) }

function Get-HealthReport([switch]$WithHelpers) {
    $out = @{}
    try {
        $watch = "$Hub\state\claude-app-watchdog.json"; $w = ReadJson $watch
        $out.claude = @{ running = [bool](Get-ClaudeAppProcesses); down_since = if ($w) { "$($w.downSince)" } else { $null }; last_ok = if ($w) { "$($w.lastOk)" } else { $null }; watchdog_at = if (Test-Path -LiteralPath $watch) { Unix (Get-Item -LiteralPath $watch).LastWriteTime } else { $null } }
    } catch { $out.claude = $null }
    try { $s = ReadJson "$Hub\state\selftest.json"; $out.selftest = if ($s) { @{ at = "$($s.at)"; failed = @($s.failed); results = $s.results } } else { $null } } catch { $out.selftest = $null }
    if ($WithHelpers) { try {
        $usage = Join-Path $Hub 'bin\usage.ps1'; $shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" }
        $tmpu = Join-Path $env:TEMP 'mc-usage-helpers.json'; Remove-Item -LiteralPath $tmpu -ErrorAction SilentlyContinue; Start-Process -FilePath $shell -ArgumentList '-NoProfile','-File',"`"$usage`"",'-Json' -RedirectStandardOutput $tmpu -WindowStyle Hidden -Wait; $u = (Get-Content -LiteralPath $tmpu -Raw -Encoding UTF8) | ConvertFrom-Json; $cw = @($u.codex.windows)[0]
        $out.helpers = @{ gemini_app = $u.gemini_app; perplexity = $u.perplexity; codex = @{ used_percent = if ($cw) { $cw.used_percent } else { $null }; resets_epoch = if ($cw) { $cw.resets_epoch } else { $null }; plan = "$($u.codex.plan)" }; parked = @($u.parked); health = $u.helper_health }
    } catch { $out.helpers = $null } } else { $out.helpers = $null }
    $out
}

# ------------------------------------------------------------------ usage

function Get-CodexUsage {
    $a = (ReadJson "$env:USERPROFILE\.codex\auth.json").tokens
    if (-not $a.access_token) { return @{ error = 'not logged in' } }
    $h = @{ Authorization = "Bearer $($a.access_token)"; 'ChatGPT-Account-Id' = "$($a.account_id)"; 'User-Agent' = 'codex_cli_rs'; originator = 'codex_cli_rs' }
    try { $u = Invoke-RestMethod -Uri 'https://chatgpt.com/backend-api/wham/usage' -Headers $h -TimeoutSec 20 }
    catch {
        $code = $_.Exception.Response.StatusCode.value__
        return @{ error = if ($code -eq 401) { 'login expired: run codex once' } else { "HTTP $code" } }
    }
    $windows = @()
    foreach ($w in @($u.rate_limit.primary_window, $u.rate_limit.secondary_window)) {
        if ($w) { $windows += @{ seconds = [int]$w.limit_window_seconds; used_pct = [double]$w.used_percent; resets_at = [double]$w.reset_at } }
    }
    @{ plan = "$($u.plan_type)"; limit_reached = [bool]$u.rate_limit.limit_reached; windows = $windows
       reset_credits = [int]$u.rate_limit_reset_credits.available_count }
}

$script:credType = $null
function Read-WinCred($target) {
    if (-not $script:credType) {
        Add-Type @'
using System; using System.Runtime.InteropServices;
public static class McCred {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public struct C { public int Flags; public int Type; public string TargetName; public string Comment; public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten; public int BlobSize; public IntPtr Blob; public int Persist; public int AttrCount; public IntPtr Attrs; public string Alias; public string User; }
  [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool CredReadW(string t, int type, int f, out IntPtr p);
  [DllImport("advapi32.dll")] static extern void CredFree(IntPtr p);
  public static byte[] Read(string t){ IntPtr p; if(!CredReadW(t,1,0,out p)) return null; var c=(C)Marshal.PtrToStructure(p,typeof(C)); var b=new byte[c.BlobSize]; Marshal.Copy(c.Blob,b,0,c.BlobSize); CredFree(p); return b; }
}
'@
        $script:credType = $true
    }
    $b = [McCred]::Read($target)
    if (-not $b) { return $null }
    $s = [Text.Encoding]::UTF8.GetString($b)
    if ($s -notmatch '^\s*[\{\[]') { $s = [Text.Encoding]::Unicode.GetString($b) }
    $s | ConvertFrom-Json
}

# Antigravity's access token lives about 1 h; when agy has not run, refresh it in memory with agy's own
# OAuth client (read from agy.exe at run time, never stored). Nothing is written back.
$script:agyClient = $null
function Get-AgyToken($cred) {
    if ([datetime]$cred.token.expiry -gt (Get-Date).AddMinutes(2)) { return $cred.token.access_token }
    $exe = "$env:LOCALAPPDATA\agy\bin\agy.exe"
    if (-not (Test-Path $exe)) { return $null }
    $pairs = if ($script:agyClient) { @($script:agyClient) } else {
        $text = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($exe))
        $ids = [regex]::Matches($text, '\d{6,}-[a-z0-9]{20,}\.apps\.googleusercontent\.com') | ForEach-Object Value | Select-Object -Unique
        $secs = [regex]::Matches($text, 'GOCSPX-[A-Za-z0-9_-]{20,40}') | ForEach-Object Value | Select-Object -Unique
        foreach ($i in $ids) { foreach ($s in $secs) { , @($i, $s) } }
    }
    foreach ($p in $pairs) {
        try {
            $r = Invoke-RestMethod -Method Post -Uri 'https://oauth2.googleapis.com/token' -TimeoutSec 15 -Body @{
                client_id = $p[0]; client_secret = $p[1]; refresh_token = $cred.token.refresh_token; grant_type = 'refresh_token' }
            $script:agyClient = $p
            return $r.access_token
        } catch { }
    }
    $null
}

function Get-AgyUsage {
    $cred = Read-WinCred 'gemini:antigravity'
    if (-not $cred) { return @{ error = 'not logged in' } }
    $tok = Get-AgyToken $cred
    if (-not $tok) { return @{ error = 'login expired: run agy once' } }
    $h = @{ Authorization = "Bearer $tok"; 'User-Agent' = 'antigravity/1.4.3 windows/amd64' }
    $u = 'https://daily-cloudcode-pa.googleapis.com/v1internal'
    try {
        $lc = Invoke-RestMethod -Method Post -Uri "$u`:loadCodeAssist" -Headers $h -ContentType 'application/json' -TimeoutSec 20 `
            -Body '{"metadata":{"ideType":"ANTIGRAVITY","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}}'
        $body = if ($lc.cloudaicompanionProject) { ConvertTo-Json @{ project = $lc.cloudaicompanionProject } -Compress } else { '{}' }
        $m = Invoke-RestMethod -Method Post -Uri "$u`:fetchAvailableModels" -Headers $h -ContentType 'application/json' -Body $body -TimeoutSec 20
    } catch { return @{ error = "HTTP $($_.Exception.Response.StatusCode.value__)" } }
    # Two families share quota pools in Antigravity: Gemini models and Claude models. Show the lowest left in each.
    $fam = @{}
    foreach ($p in $m.models.PSObject.Properties) {
        $q = $p.Value.quotaInfo
        if ($null -eq $q -or $null -eq $q.remainingFraction -or -not $q.resetTime) { continue }
        $f = if ($p.Name -like 'claude*') { 'claude' } elseif ($p.Name -like 'gemini*') { 'gemini' } else { continue }
        $left = [double]$q.remainingFraction
        $reset = Unix ([datetime]$q.resetTime)
        if (-not $fam[$f] -or $left -lt $fam[$f].left) { $fam[$f] = @{ left = $left; resets_at = $reset } }
    }
    $windows = @()
    foreach ($f in 'gemini', 'claude') {
        if ($fam[$f]) {
            $secs = [int][Math]::Max(0, $fam[$f].resets_at - [DateTimeOffset]::Now.ToUnixTimeSeconds())
            $windows += @{ name = "$f models"; used_pct = [Math]::Round((1 - $fam[$f].left) * 100, 1); resets_at = $fam[$f].resets_at
                           seconds = if ($secs -gt 86400) { 604800 } else { 18000 } }
        }
    }
    @{ plan = "$($lc.paidTier.id)"; windows = $windows }
}

function Get-ClaudeUsage {
    $c = ReadJson "$Hub\state\usage-claude.json"
    if (-not $c) { return @{ error = 'no data yet (status line writes it while Claude Code runs)' } }
    $windows = @()
    foreach ($n in 'five_hour', 'seven_day') {
        $w = $c.windows.$n
        if ($w) { $windows += @{ name = $n; seconds = if ($n -eq 'five_hour') { 18000 } else { 604800 }; used_pct = $w.used_pct; resets_at = $w.resets_at } }
    }
    @{ windows = $windows; source_at = $c.at }
}

function Get-GeminiUsage {
    # No usage API for API keys or the Gemini app: show what the hub itself counts.
    $app = ReadJson "$Hub\state\gemini-app-count.json"
    $today = (Get-Date -Format 'yyyy-MM-dd')
    $jobs = if ($app -and $app.date -eq $today) { [int]$app.count } else { 0 }
    @{ app_jobs_today = $jobs; app_jobs_max = 25 }
}

function Get-Parked {
    $c = ReadJson "$Hub\state\cooldown.json"
    $now = [DateTimeOffset]::Now.ToUnixTimeSeconds()
    $out = @{}
    if ($c) { foreach ($p in $c.PSObject.Properties) { if ([double]$p.Value -gt $now) { $out[$p.Name] = [double]$p.Value } } }
    $out
}

function Get-Usage {
    $u = @{}
    foreach ($pair in @(@('claude', { Get-ClaudeUsage }), @('codex', { Get-CodexUsage }), @('gemini', { Get-GeminiUsage }), @('antigravity', { Get-AgyUsage }))) {
        try { $u[$pair[0]] = & $pair[1] } catch { $u[$pair[0]] = @{ error = $_.Exception.Message } }
        $u[$pair[0]].at = [DateTimeOffset]::Now.ToUnixTimeSeconds()
    }
    $u
}

# ------------------------------------------------------------------ live stats + screenshot (stage 6)

function Get-LhmCpuTemp {
    # LibreHardwareMonitor (admin, started at logon by a scheduled task) serves its sensors as JSON on
    # localhost:8085 (this version has no WMI provider). Read-only, local only.
    try {
        $j = (Invoke-WebRequest 'http://127.0.0.1:8085/data.json' -UseBasicParsing -TimeoutSec 3).Content | ConvertFrom-Json
        $found = $null
        function Find-Cpu($n) {
            foreach ($c in $n.Children) {
                if ($c.SensorId -match '^/(amdcpu|intelcpu)/\d+/temperature/' -and $c.Text -match 'Package|Tctl|Tdie' -and -not $script:found) {
                    $script:found = $c.Value
                }
                Find-Cpu $c
            }
        }
        $script:found = $null
        Find-Cpu $j
        if ($script:found -match '([\d]+[.,]?[\d]*)') { return [double]($Matches[1] -replace ',', '.') }
    } catch { }
    $null
}

function Get-PcStats {
    $o = @{}
    try {
        $g = (& nvidia-smi --query-gpu=temperature.gpu,utilization.gpu --format=csv,noheader,nounits 2>$null) -split ','
        if ($g.Count -ge 2) { $o.gpu_temp = [double]$g[0].Trim(); $o.gpu_load = [double]$g[1].Trim() }
    } catch { }
    try { $o.cpu_load = [double](Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average } catch { }
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $o.ram_pct = [Math]::Round(100 * (1 - $os.FreePhysicalMemory / $os.TotalVisibleMemorySize), 1)
    } catch { }
    $t = Get-LhmCpuTemp
    if ($null -ne $t) { $o.cpu_temp = $t }
    $o
}

function Send-Screenshot {
    # Windows' antivirus (AMSI) blocks a PowerShell script that captures the screen, so a tiny separate Python
    # script (mc-shot.py) does it. It reads mc-pc.json itself, sends the JPEG to mc-pi, and nothing is saved.
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { Write-Log 'screenshot: python not found'; return }
    $out = & $py -I (Join-Path $here 'mc-shot.py') 2>&1 | Out-String
    Write-Log "screenshot: $($out.Trim())"
}

# ------------------------------------------------------------------ report

function Tail-Logs {
    $o = @{}
    foreach ($f in Get-ChildItem "$Hub\status\*.log" -ErrorAction SilentlyContinue) {
        $t = (Get-Content -LiteralPath $f.FullName -Tail 15 -Encoding UTF8) -join "`n"
        if ($t.Length -gt 4000) { $t = $t.Substring($t.Length - 4000) }
        $o[$f.BaseName] = @{ text = $t; at = Unix $f.LastWriteTime }
    }
    $o
}

function Handoff-Summary {
    $f = "$Hub\HANDOFF.md"
    if (-not (Test-Path $f)) { return '' }
    $keep = $false; $out = New-Object System.Collections.Generic.List[string]
    foreach ($l in Get-Content -LiteralPath $f -Encoding UTF8) {
        if ($l -match '^## ') { $keep = $l -match '^## (Current task|Status)' }
        if ($keep) { $out.Add($l) }
    }
    $s = $out -join "`n"
    if ($s.Length -gt 4000) { $s = $s.Substring(0, 4000) + "`n…" }
    $s
}

$script:uploaded = @{}    # "<id>/<n>" -> $true
function Pending-Approvals {
    $list = @()
    foreach ($f in Get-ChildItem "$Hub\approvals\pending\*.json" -ErrorAction SilentlyContinue) {
        try { $a = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json } catch { continue }
        $pics = @($a.pictures)
        for ($i = 0; $i -lt $pics.Count; $i++) {
            $key = "$($a.id)/$i"
            if ($script:uploaded[$key] -or -not (Test-Path -LiteralPath $pics[$i])) { continue }
            try {
                Api 'Post' "/api/pc/picture?approval=$($a.id)&n=$i" (Shrink-Picture $pics[$i]) 'image/jpeg' | Out-Null
                $script:uploaded[$key] = $true
            } catch { Write-Log "picture upload failed ($key): $($_.Exception.Message)" }
        }
        $list += @{ id = "$($a.id)"; type = "$($a.type)"; title = "$($a.title)"; text = "$($a.text)"; options = @($a.options)
                    pictures = $pics.Count; session = "$($a.session)"; created = [double]$a.created }
    }
    , $list
}

function Shrink-Picture($path) {
    $img = [System.Drawing.Image]::FromFile($path)
    try {
        $scale = [Math]::Min(1.0, 1280.0 / [Math]::Max($img.Width, $img.Height))
        $w = [int]($img.Width * $scale); $h = [int]($img.Height * $scale)
        $bmp = New-Object System.Drawing.Bitmap $w, $h
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.InterpolationMode = 'HighQualityBicubic'
        $g.DrawImage($img, 0, 0, $w, $h); $g.Dispose()
        $ms = New-Object IO.MemoryStream
        $enc = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object MimeType -eq 'image/jpeg'
        $ep = New-Object System.Drawing.Imaging.EncoderParameters 1
        $ep.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter ([System.Drawing.Imaging.Encoder]::Quality), 82L
        $bmp.Save($ms, $enc, $ep); $bmp.Dispose()
        , $ms.ToArray()
    } finally { $img.Dispose() }
}

# ------------------------------------------------------------------ answers and ideas -> D:\ai-hub

function Write-InboxMessage($topic, $body) {
    $dir = "$Hub\inbox\claude"
    New-Item -ItemType Directory -Force $dir | Out-Null
    $now = Get-Date
    $name = "$($now.ToString('yyyy-MM-dd-HHmm'))-from-filip-$topic.md"
    $path = Join-Path $dir $name
    $n = 2; while (Test-Path -LiteralPath $path) { $path = Join-Path $dir ($name -replace '\.md$', "-$n.md"); $n++ }
    [IO.File]::WriteAllText($path, $body, $utf8)
    $path
}

function Handle-Item($it) {
    $date = (Get-Date -Format 'yyyy-MM-dd HH:mm')
    if ($it.kind -eq 'claude-restart') {
        $r = Restart-ClaudeApp; Send-Result $it.key ([bool]$r.ok) $r.detail
    } elseif ($it.kind -eq 'bitwarden-open') {
        $r = Open-Bitwarden; Send-Result $it.key ([bool]$r.ok) $r.detail
    } elseif ($it.kind -eq 'pc-mode') {
        Start-ModeSwitch $it
    } elseif ($it.kind -eq 'localai-report') {
        try { Send-LocalAiReport $it } catch { Send-Result $it.key $false $_.Exception.Message }
    } elseif ($it.kind -eq 'rc-queue') {
        $py = (Get-Command python -ErrorAction SilentlyContinue).Source
        if (-not $py) { Send-Result $it.key $false 'python not found on the PC'; return }
        $env:MC_ITEM = ConvertTo-Json @{ id = "$($it.id)"; local = "$($it.local)"; title = "$($it.title)" } -Compress; $env:MC_HUB = $Hub
        try { $r = (& $py -I (Join-Path $here 'mc_health.py') 2>$null | Out-String) | ConvertFrom-Json } catch { $r = @{ ok = $false; detail = $_.Exception.Message } } finally { Remove-Item Env:MC_ITEM,Env:MC_HUB -ErrorAction SilentlyContinue }
        Send-Result $it.key ([bool]$r.ok) "$($r.detail)"
    } elseif ($it.kind -eq 'helper-answer') {
        $py = (Get-Command python -ErrorAction SilentlyContinue).Source
        if (-not $py) { Send-Result $it.key $false 'python not found on the PC'; return }
        $env:MC_ITEM = ConvertTo-Json @{ id = "$($it.id)"; text = "$($it.text)" } -Compress; $env:MC_HUB = $Hub
        try { $r = (& $py -I (Join-Path $here 'mc_digest.py') answer 2>$null | Out-String) | ConvertFrom-Json } catch { $r = @{ ok = $false; detail = $_.Exception.Message } } finally { Remove-Item Env:MC_ITEM,Env:MC_HUB -ErrorAction SilentlyContinue }
        Write-Log "helper question $($it.id): $($r.detail)"
        Send-Result $it.key ([bool]$r.ok) "$($r.detail)"
    } elseif ($it.kind -eq 'answer') {
        $pend = "$Hub\approvals\pending\$($it.id).json"
        $req = ReadJson $pend
        $title = if ($req) { $req.title } else { $it.title }
        $ans = [ordered]@{ id = $it.id; decision = $it.decision; option = $it.option; text = $it.text
                           title = $title; answered_at = $it.at; signed = $true }
        New-Item -ItemType Directory -Force "$Hub\approvals\answered" | Out-Null
        # The answer file first: approval.ps1 treats a vanished pending file without an answer as withdrawn.
        [IO.File]::WriteAllText("$Hub\approvals\answered\$($it.id).json", (ConvertTo-Json $ans -Depth 4), $utf8)
        if (Test-Path -LiteralPath $pend) { Remove-Item -LiteralPath $pend }
        $what = switch ($it.decision) { 'approve' { 'Approved' } 'reject' { 'Rejected' } 'option' { "Picked: $($it.option)" } default { 'Replied' } }
        $msg = "# Approval answer: $title`nFrom: filip   To: claude   Date: $date`n## Task`n$what (fingerprint-confirmed in Mission Control). Approval id: $($it.id)" +
               $(if ($req.session) { ", session: $($req.session)" } else { '' }) + "`n" +
               $(if ($it.text) { "`nFilip's note:`n$($it.text)`n" } else { '' }) +
               "## Files`nD:\ai-hub\approvals\answered\$($it.id).json`n## Done when`nThe session that asked has acted on the answer.`n"
        Write-InboxMessage "approval-$($it.id)" $msg | Out-Null
        Write-Log "answer $($it.id): $($it.decision)"
    } elseif ($it.kind -eq 'gate') {
        # Filip's fingerprint-signed answer to a phone-gate request (permission or question).
        $pend = "$Hub\gate\pending\$($it.id).json"
        if (-not (Test-Path -LiteralPath $pend)) { Write-Log "gate $($it.id): already answered at the PC"; Send-Result $it.key $false 'answered at the PC first'; return }
        New-Item -ItemType Directory -Force "$Hub\gate\answered" | Out-Null
        $ans = @{ decision = $it.decision; text = $it.text; answers = $it.answers }
        [IO.File]::WriteAllText("$Hub\gate\answered\$($it.id).json", (ConvertTo-Json $ans -Depth 6), $utf8)
        Write-Log "gate $($it.id): $($it.decision)"
        Send-Result $it.key $true 'answered'
    } elseif ($it.kind -eq 'appcard') {
        Answer-AppCard $it
    } elseif ($it.kind -eq 'gate-config') {
        New-Item -ItemType Directory -Force "$Hub\gate" | Out-Null
        [IO.File]::WriteAllText("$Hub\gate\config.json", (ConvertTo-Json @{ auto = "$($it.auto)"; enabled = [bool]$it.enabled }), $utf8)
        Write-Log "gate config: auto=$($it.auto) enabled=$($it.enabled)"
    } elseif ($it.kind -eq 'skola-new') {
        Save-SkolaTask $it
    } elseif ($it.kind -eq 'message') {
        Send-Typed $it
    } elseif ($it.kind -eq 'idea') {
        $audio = ''
        if ($it.audio_id) {
            $dir = "$Hub\inbox\claude\audio"; New-Item -ItemType Directory -Force $dir | Out-Null
            $audio = Join-Path $dir "$((Get-Date).ToString('yyyy-MM-dd-HHmmss'))-idea.m4a"
            Invoke-WebRequest -Uri "$base/api/pc/audio/$($it.audio_id)" -Headers $headers -OutFile $audio -TimeoutSec 60 -UseBasicParsing
        }
        $text = if ($it.text) { $it.text } else { '(audio only, not transcribed yet)' }
        $msg = "# Idea from Filip`nFrom: filip   To: claude   Date: $date`n## Task`n$text`n## Files`n" +
               $(if ($audio) { $audio } else { '(none)' }) + "`n## Done when`nClaude has read it and told Filip what it will do with it.`n"
        Write-InboxMessage 'idea' $msg | Out-Null
        Write-Log 'idea saved to inbox'
    }
}

# ------------------------------------------------------------------ Claude sessions (claude tab v2)

# Helper questions (stage 11b): the open ones, re-read only when the inbox listing changed.
$script:questionSig = $null; $script:questions = @()
function Get-OpenQuestions {
    $names = @(Get-ChildItem "$Hub\inbox\claude\*-question-*.md" -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
    $sig = $names -join '|'
    if ($sig -ne $script:questionSig) {
        $script:questions = @()
        if ($names.Count) {
            $py = (Get-Command python -ErrorAction SilentlyContinue).Source
            if ($py) {
                $env:MC_HUB = $Hub
                try { $script:questions = @((& $py -I (Join-Path $here 'mc_digest.py') questions 2>$null | Out-String) | ConvertFrom-Json) } catch { Write-Log "questions: $($_.Exception.Message)" } finally { Remove-Item Env:MC_HUB -ErrorAction SilentlyContinue }
            }
        }
        $script:questionSig = $sig
    }
    ,$script:questions
}

# Daily digest (stage 11b): computed here when the Pi asks (`digest` in the command reply), sent to the Pi.
function Send-Digest {
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { throw 'python not found on the PC' }
    $env:MC_HUB = $Hub
    try { $json = (& $py -I (Join-Path $here 'mc_digest.py') digest 2>$null | Out-String) } finally { Remove-Item Env:MC_HUB -ErrorAction SilentlyContinue }
    $d = $json | ConvertFrom-Json
    if (-not $d.text) { throw 'digest came back empty' }
    Api 'Post' '/api/pc/digest' @{ date = $d.date; text = $d.text; summary = $d.summary; counts = $d.counts } | Out-Null
    Write-Log "digest sent ($($d.summary))"
}

function Send-Result($key, $ok, $detail) {
    try { Api 'Post' '/api/pc/result' @{ key = $key; ok = $ok; detail = "$detail" } | Out-Null } catch { Write-Log "result: $($_.Exception.Message)" }
}

function Restart-ClaudeApp([switch]$DryRun) {
    $procs = @(Get-ClaudeAppProcesses)
    if ($DryRun) { Write-Log "Claude restart dry run: would stop $($procs.Count) process(es) and start Claude"; return @{ ok = $true; detail = 'dry run' } }
    try {
        Write-Log "Claude restart: stopping $($procs.Count) process(es)"; foreach ($p in $procs) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
        $until = (Get-Date).AddSeconds(10); while ((Get-Date) -lt $until -and @(Get-ClaudeAppProcesses).Count) { Start-Sleep -Milliseconds 300 }
        $alias = "$env:LOCALAPPDATA\Microsoft\WindowsApps\claude-desktop.exe"
        if (Test-Path -LiteralPath $alias) { Start-Process -FilePath $alias -ArgumentList '--startup' } else { Start-Process explorer.exe 'shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude' }
        $until = (Get-Date).AddSeconds(30); while ((Get-Date) -lt $until) { if (@(Get-ClaudeAppProcesses).Count) { return @{ ok = $true; detail = 'restarted' } }; Start-Sleep -Seconds 1 }
        return @{ ok = $false; detail = 'did not come back' }
    } catch { Write-Log "Claude restart failed: $($_.Exception.Message)"; return @{ ok = $false; detail = 'did not come back' } }
}

function Find-Bitwarden {
    # Installer build first, then the Microsoft Store build (shell:AppsFolder AUMID). Read-only: only paths and app names.
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Bitwarden\Bitwarden.exe", "$env:ProgramFiles\Bitwarden\Bitwarden.exe")) {
        if (Test-Path -LiteralPath $p) { return @{ kind = 'exe'; target = $p } }
    }
    try {
        $pkg = Get-AppxPackage -Name '*Bitwarden*' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pkg) {
            $app = Get-StartApps | Where-Object { $_.AppID -like "$($pkg.PackageFamilyName)!*" } | Select-Object -First 1
            if ($app) { return @{ kind = 'aumid'; target = $app.AppID } }
        }
    } catch { }
    return $null
}

function Open-Bitwarden([switch]$DryRun) {
    # Design A (Filip): only opens / focuses Bitwarden desktop. No vault data, no secrets, fixed arguments only.
    $found = Find-Bitwarden
    if (-not $found) { return @{ ok = $false; detail = 'Bitwarden desktop not installed' } }
    $locked = [bool](Get-Process LogonUI -ErrorAction SilentlyContinue)
    $procs = @(Get-Process Bitwarden -ErrorAction SilentlyContinue)
    if ($DryRun) { Write-Log "Bitwarden dry run: $($found.kind) $($found.target), running=$($procs.Count), locked=$locked"; return @{ ok = $true; detail = 'dry run'; kind = $found.kind; running = $procs.Count } }
    try {
        $focused = $false
        $win = $procs | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
        if ($win -and -not $locked) {
            if (-not ('McWin' -as [type])) {
                Add-Type @'
using System; using System.Runtime.InteropServices;
public static class McWin {
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
'@
            }
            if ([McWin]::IsIconic($win.MainWindowHandle)) { [McWin]::ShowWindowAsync($win.MainWindowHandle, 9) | Out-Null }
            $focused = [McWin]::SetForegroundWindow($win.MainWindowHandle)
        }
        if (-not $focused) {
            # Not running, hidden in the tray, or the lock screen is up: start it (the single-instance app shows its own window).
            if ($found.kind -eq 'exe') { Start-Process -FilePath $found.target } else { Start-Process explorer.exe "shell:AppsFolder\$($found.target)" }
        }
        $detail = if ($focused) { 'focused' } else { 'opened' }
        if ($locked) { $detail = 'PC is locked (Bitwarden started, unlock the PC)' }
        Write-Log "Bitwarden: $detail"
        return @{ ok = $true; detail = $detail }
    } catch { Write-Log "Bitwarden open failed: $($_.Exception.Message)"; return @{ ok = $false; detail = 'could not start Bitwarden' } }
}

$script:typeCodes = @{ 0 = 'sent'; 2 = 'bad message'; 3 = 'PC is locked'; 5 = 'there is a draft in that session''s prompt box'
                      6 = 'could not find the session in Claude Desktop'; 7 = 'a different session opened' }
$script:waitTold = @{}
function Send-Typed($it) {
    # A message (or "Start" for a proposed session) typed into Claude Desktop. Waits while the PC is locked (no idle check).
    if ([DateTimeOffset]::Now.ToUnixTimeSeconds() - [double]$it.at -gt 1800) { Send-Result $it.key $false 'expired: the PC was locked for 30 min'; return }
    # No idle check (Filip, 2026-11-15): a message sent from the phone means he is not at the PC. Only a locked PC waits.
    $why = if (Get-Process LogonUI -ErrorAction SilentlyContinue) { 'PC is locked' } else { $null }
    if ($why) {
        if (-not $script:waitTold[$it.key]) { $script:waitTold[$it.key] = $true; Send-Result $it.key $null "waiting: $why" }
        throw "waiting: $why"                              # not acked: tried again on the next poll
    }
    $tmp = Join-Path $env:TEMP "mc-type-$($it.key).txt"
    [IO.File]::WriteAllText($tmp, "$($it.text)", $utf8)
    try {
        $out = & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass `
            -File (Join-Path $here 'mc-type.ps1') -Local "$($it.local)" -Title "$($it.title)" -TextFile $tmp 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally { Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue }
    $why = $script:typeCodes[[int]$code]; if (-not $why) { $why = "error $code" }
    Write-Log "message to '$($it.title)': $why $($out.Trim())"
    if ($code -eq 3) { throw "waiting: $why" }          # not acked: tried again on the next poll
    Send-Result $it.key ($code -eq 0) $why
}
# ------------------------------------------------------------------ the desktop app's own approval cards (stage 11a-1)

$script:cardWaitTold = @{}
function Answer-AppCard($it) {
    # Filip's answer to an app card (Allow signed with his fingerprint on the Pi, Deny one tap). mc_appgate.py decides:
    # expired (8 h) / gone (answered at the PC) / held (PC locked: not acked, tried again next poll) / clicked / refused.
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { Send-Result $it.key $false 'python not found on the PC'; return }
    $env:MC_ITEM = (ConvertTo-Json @{ card = "$($it.card)"; decision = "$($it.decision)"; title = "$($it.title)"
                                      tool = "$($it.tool)"; at = [double]$it.at } -Compress)
    try { $raw = & $py -I (Join-Path $here 'mc_appgate.py') answer 2>$null | Out-String } finally { Remove-Item Env:MC_ITEM -ErrorAction SilentlyContinue }
    $r = $null
    try { $r = $raw | ConvertFrom-Json } catch { }
    if (-not $r) { Write-Log "appcard $($it.card): no answer from mc_appgate.py"; Send-Result $it.key $false 'refused: PC helper error'; return }
    if ($r.state -eq 'held') {
        if (-not $script:cardWaitTold[$it.key]) { Write-Log "appcard $($it.card) $($it.decision): $($r.detail)"; Send-Result $it.key $null $r.detail; $script:cardWaitTold[$it.key] = 1 }
        throw "waiting: $($r.detail)"                       # not acked: tried again on the next poll
    }
    $script:cardWaitTold.Remove($it.key)
    Write-Log "appcard $($it.card) $($it.decision) '$($it.title)': $($r.state) $($r.detail)"
    Send-Result $it.key ([bool]$r.ok) $r.detail
}

$script:cardShots = @{}
function Send-CardShots {
    # A fresh PC screenshot for every approval / question / app card the phone has not got one for yet (mc-shot.py sends
    # a small JPEG, or "PC locked" when the PC is locked; nothing is saved; the Pi drops it when the card is gone). Stage 11e.
    $snap = ReadJson (Join-Path $env:TEMP 'mc-sessions.json')
    if (-not $snap) { return }
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { return }
    foreach ($g in @($snap.gates | Where-Object { $_.kind -in 'appcard', 'permission', 'question' })) {
        $id = "$($g.id)"
        if ($id -notmatch '^(ac-[0-9a-f-]{36}|[0-9]{8}-[0-9]{6}-[0-9a-f]{4})$' -or $script:cardShots[$id]) { continue }
        $script:cardShots[$id] = 1
        $out = & $py -I (Join-Path $here 'mc-shot.py') --gate $id 2>&1 | Out-String
        Write-Log "card $id screenshot: $($out.Trim())"
    }
}

$script:sessionsAt = [datetime]::MinValue
# ------------------------------------------------------------------ PC mode + Local AI card (0.15)

$script:modeJob = $null      # the pc-mode.ps1 run started from the phone: @{ key; proc; out; mode; model; started }
$script:nextLocalAi = Get-Date
function Get-PythonExe { (Get-Command python -ErrorAction SilentlyContinue).Source }

function Get-PcModeReport {
    # pc-mode.json through mc_localai.py (it converts the local `since` time to unix seconds). $null when unreadable.
    try {
        $py = Get-PythonExe; if (-not $py) { return $null }
        $m = (& $py -I (Join-Path $here 'mc_localai.py') mode 2>$null | Out-String) | ConvertFrom-Json
        if ($m.mode) { return $m }
    } catch { }
    $null
}

function Get-LocalAiJson {
    $py = Get-PythonExe; if (-not $py) { return $null }
    $text = (& $py -I (Join-Path $here 'mc_localai.py') 2>$null | Out-String)
    if ($LASTEXITCODE -ne 0 -or -not $text.Trim()) { return $null }
    $text
}

function Send-LocalAi {
    $text = Get-LocalAiJson
    if (-not $text) { return }
    Api 'Post' '/api/pc/localai' ([byte[]]$utf8.GetBytes($text)) | Out-Null
}

function Start-ModeSwitch($it) {
    # pc-mode.ps1 takes ~60 s for AI (and may wait up to 240 s for its own mutex): start it hidden and poll it
    # from the main loop instead of blocking here. Only fixed values reach the command line.
    $mode = "$($it.mode)"; $model = "$($it.model)"
    if (@('normal', 'ai', 'gaming') -notcontains $mode -or @('', 'qwen', 'gptoss') -notcontains $model) { Send-Result $it.key $false 'bad mode request'; return }
    if ($mode -ne 'ai') { $model = '' }
    if ($script:modeJob -and -not $script:modeJob.proc.HasExited) { Send-Result $it.key $false 'a switch is already running'; return }
    $modeScript = Join-Path $Hub 'bin\pc-mode.ps1'
    if (-not (Test-Path -LiteralPath $modeScript)) { Send-Result $it.key $false 'pc-mode.ps1 not found'; return }
    $shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" }
    $out = Join-Path $env:TEMP "mc-pc-mode-$([int](Unix (Get-Date))).txt"
    $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$modeScript`"", '-Mode', $mode)
    if ($model) { $a += @('-Model', $model) }
    $a += '-Quiet'
    $p = Start-Process -FilePath $shell -ArgumentList $a -WindowStyle Hidden -PassThru -RedirectStandardOutput $out
    $null = $p.Handle      # keeps the exit code readable after the process ends
    $script:modeJob = @{ key = $it.key; proc = $p; out = $out; mode = $mode; model = $model; started = Get-Date }
    Write-Log "pc-mode $mode $model started from the phone (pid $($p.Id))"
}

function Check-ModeJob {
    $j = $script:modeJob
    if (-not $j) { return }
    if (-not $j.proc.HasExited) {
        if (((Get-Date) - $j.started).TotalSeconds -gt 420) { Write-Log 'pc-mode run took over 7 min: giving up waiting'; Stop-Process -Id $j.proc.Id -Force -ErrorAction SilentlyContinue; Send-Result $j.key $false 'timed out'; $script:modeJob = $null }
        return
    }
    $code = $j.proc.ExitCode
    $text = ''; try { $text = (Get-Content -LiteralPath $j.out -Raw -ErrorAction SilentlyContinue) } catch { }
    Remove-Item -LiteralPath $j.out -ErrorAction SilentlyContinue
    $script:modeJob = $null
    Write-Log "pc-mode $($j.mode) finished, exit $code"
    # the real mode state first (the Pi shows it at once), then the result
    try { Send-LocalAi } catch { Write-Log "localai: $($_.Exception.Message)" }
    $detail = if ($code -eq 0) { "mode=$($j.mode)" } else { "exit $code $(("$text").Trim())" }
    if ($detail.Length -gt 180) { $detail = $detail.Substring(0, 180) }
    Send-Result $j.key ($code -eq 0) $detail
}

function Send-LocalAiReport($it) {
    $file = Join-Path $Hub 'files\local-agent-trials\report.md'
    if (-not (Test-Path -LiteralPath $file)) { Send-Result $it.key $false 'report.md does not exist'; return }
    $text = [IO.File]::ReadAllText($file, $utf8)
    $r = Api 'Post' '/api/pc/docs/upload' @{ kind = 'doc'; name = 'local-agent-trials-report.md'; text = $text; source = $file; title = 'Local agent trials report' }
    Send-Result $it.key $true "$($r.slug)"
}

function Send-Sessions($watch) {
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { return }
    $out = Join-Path $env:TEMP 'mc-sessions.json'
    $pargs = @('-I', (Join-Path $here 'mc_sessions.py'), '--out', $out)
    if ($watch -match '^[0-9a-f-]{36}$') { $pargs += @('--watch', $watch) }
    & $py @pargs 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $out)) { return }
    Api 'Post' '/api/pc/sessions' ([IO.File]::ReadAllBytes($out)) | Out-Null
}

# ------------------------------------------------------------------ Docs & Checklists (stage 5)

function Sync-Docs {
    # Claude -> phone: Markdown dropped into to-phone\checklists or to-phone\docs.
    $sent = "$Hub\to-phone\sent"
    foreach ($kind in 'checklists', 'docs') {
        $dir = "$Hub\to-phone\$kind"
        New-Item -ItemType Directory -Force $dir, $sent | Out-Null
        foreach ($f in Get-ChildItem "$dir\*.md" -ErrorAction SilentlyContinue) {
            $text = [IO.File]::ReadAllText($f.FullName, $utf8)
            $body = @{ kind = $kind.TrimEnd('s'); name = $f.Name; text = $text }
            # mc-doc.ps1 leaves a sidecar <name>.md.owner.json: the session that published the file and where it came from
            $side = "$($f.FullName).owner.json"
            if (Test-Path -LiteralPath $side) {
                try {
                    $o = ReadJson $side
                    $osid = "$($o.sid)"; if ($osid -notmatch '^[0-9a-f-]{36}$') { $osid = '' }
                    $body.owner = @{ sid = $osid; title = "$($o.title)"; cwd = "$($o.cwd)" }
                    $body.source = "$($o.source)"
                } catch { Write-Log "owner sidecar of $($f.Name): $($_.Exception.Message)" }
            }
            $r = Api 'Post' '/api/pc/docs/upload' $body
            Move-Item -LiteralPath $f.FullName -Destination (Join-Path $sent ((Get-Date -Format 'yyyyMMdd-HHmmss-') + $f.Name)) -Force
            if (Test-Path -LiteralPath $side) { Remove-Item -LiteralPath $side -ErrorAction SilentlyContinue }
            Write-Log "sent to phone: $kind\$($f.Name) ($($r.slug))"
        }
    }
    # Phone -> Claude: results, comments, edits, screenshots; Finish / Send to Claude as inbox messages.
    $c = Api 'Get' '/api/pc/docs/changes'
    $acks = @()
    foreach ($ch in @($c.changes)) {
        if (-not $ch) { continue }
        $dir = if ($ch.kind -eq 'checklist') { "$Hub\files\checklists\$($ch.slug)" } else { "$Hub\files\docs\$($ch.slug)" }   # docs, plans and school outputs
        New-Item -ItemType Directory -Force $dir | Out-Null
        if ($ch.kind -eq 'checklist') { [IO.File]::WriteAllText("$dir\results.md", $ch.export, $utf8) }
        else {
            [IO.File]::WriteAllText("$dir\comments.md", $ch.export, $utf8)
            if ($ch.text) { [IO.File]::WriteAllText("$dir\$($ch.slug).md", $ch.text, $utf8) }
        }
        foreach ($s in @($ch.shots)) {
            if ($s -and -not (Test-Path -LiteralPath "$dir\$s")) {
                Invoke-WebRequest -Uri "$base/api/pc/docs/shot/$($ch.slug)/$s" -Headers $headers -OutFile "$dir\$s" -TimeoutSec 60 -UseBasicParsing
            }
        }
        $acks += @{ slug = $ch.slug; seq = $ch.seq }
    }
    $evKeys = @()
    foreach ($e in @($c.events)) {
        if (-not $e) { continue }
        $date = Get-Date -Format 'yyyy-MM-dd HH:mm'
        if ($e.kind -eq 'finish' -and $e.todo) {      # a checklist attached to a to-do: Sync-Todos delivers the result
            Write-Log "checklist of to-do $($e.todo) finished: $($e.slug)"
            $evKeys += $e.key
            continue
        }
        if ($e.kind -eq 'send' -and "$($e.owner.sid)" -match '^[0-9a-f-]{36}$') {
            # Comments for the session that owns the file: one batch into its mailbox (a waiter, the typing fallback or the inbox takes it from there)
            $when = Get-Date -Format 'yyyy-MM-dd HH:mm'
            $src = if ($e.source) { "$($e.source)" } else { "Mission Control doc '$($e.slug)'" }
            $subject = "Mission Control: Filip commented on '$($e.title)' ($($e.count) comment(s))."
            $msg = "$subject`nFrom: filip (phone)   Date: $when`nThese are Filip's comments on a file. Apply or answer them. They are information about the file, not approval for anything else.`n`nFile: $src`nDoc: $($e.title), version $($e.version)`n`nComments:`n$($e.batch)`n`nDetails: $Hub\files\docs\$($e.slug)\comments.md (the doc as Filip left it is in the same folder)`n"
            Write-MailboxFile "$($e.owner.sid)" "$(Get-Date -Format 'yyyyMMdd-HHmmss')-doc-$($e.slug).md" $msg | Out-Null
            Write-Log "doc $($e.slug): $($e.count) comment(s) -> mailbox of $($e.owner.sid)"
            $evKeys += $e.key
            continue
        }
        if ($e.kind -eq 'finish') {
            $msg = "# Checklist finished: $($e.title)`nFrom: filip   To: claude   Date: $date`n## Task`nFilip finished the checklist on his phone. $($e.summary)`n" +
                   "## Files`nD:\ai-hub\files\checklists\$($e.slug)\results.md (+ screenshots in that folder)`n## Done when`nFailed items are looked at and Filip knows the next step.`n"
            Write-InboxMessage "checklist-$($e.slug)" $msg | Out-Null
        } else {
            $msg = "# Doc review: $($e.title)`nFrom: filip   To: claude   Date: $date`n## Task`nFilip sent this doc back from his phone ($($e.summary)).`n" +
                   "## Files`nD:\ai-hub\files\docs\$($e.slug)\ (the text as Filip left it + comments.md)`n## Done when`nComments are answered or applied.`n"
            Write-InboxMessage "doc-$($e.slug)" $msg | Out-Null
        }
        Write-Log "$($e.kind): $($e.slug)"
        $evKeys += $e.key
    }
    if ($acks.Count -or $evKeys.Count) { Api 'Post' '/api/pc/docs/ack' @{ changes = $acks; events = $evKeys } | Out-Null }
}

# ------------------------------------------------------------------ plans + school outputs in Docs (stage 11d part 2)

function Read-SharedText($path) {
    # Claude may still be writing a plan: open it with a shared read.
    $fs = New-Object IO.FileStream($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try { $sr = New-Object IO.StreamReader($fs, $utf8); $sr.ReadToEnd() } finally { $fs.Dispose() }
}

$script:planSeen = @{}       # plan name -> "mtime|size|owner" last uploaded
function Sync-Plans {
    # Every ~/.claude/plans/*.md goes to Docs as kind "plan", with the session that owns it (mc_sessions.py found it through the
    # "slug" field on transcript lines). Cheap: it only compares the list mc_sessions.py wrote; the file is read when it changed.
    $snap = Get-SessionSnap
    if (-not $snap -or -not $snap.plans) { return }
    $dir = Join-Path $env:USERPROFILE '.claude\plans'
    foreach ($p in @($snap.plans)) {
        $slug = "$($p.slug)"
        if ($slug -notmatch '^[A-Za-z0-9._-]{3,100}$') { continue }
        $osid = "$($p.owner.sid)"; if ($osid -notmatch '^[0-9a-f-]{36}$') { $osid = '' }
        $key = "$($p.mtime)|$($p.size)|$osid"
        if ($script:planSeen[$slug] -eq $key) { continue }
        $file = Join-Path $dir "$slug.md"
        if (-not (Test-Path -LiteralPath $file)) { continue }
        $script:planSeen[$slug] = $key                       # also when the upload fails: it is logged once, not every 5 s
        $text = Read-SharedText $file
        Api 'Post' '/api/pc/docs/upload' @{ kind = 'plan'; name = "plan-$slug"; text = $text; source = $file
            owner = @{ sid = $osid; title = "$($p.owner.title)"; cwd = "$($p.owner.cwd)" } } | Out-Null
        Write-Log "plan sent to phone: $slug (session $(if ($osid) { $osid } else { 'unknown' }))"
    }
}

function Sync-Skola {
    # skola-publish.ps1 leaves a folder in to-phone\skola\<id>\ (meta.json, review.md, output.pdf); it goes to the Pi as kind "skola".
    $root = "$Hub\to-phone\skola"; $sent = "$Hub\to-phone\sent"
    if (-not (Test-Path -LiteralPath $root)) { return }
    foreach ($d in Get-ChildItem $root -Directory -ErrorAction SilentlyContinue) {
        if (-not (Test-Path -LiteralPath "$($d.FullName)\ready")) { continue }       # the script writes "ready" last
        $m = ReadJson "$($d.FullName)\meta.json"
        $review = if (Test-Path -LiteralPath "$($d.FullName)\review.md") { [IO.File]::ReadAllText("$($d.FullName)\review.md", $utf8) } else { '' }
        $osid = "$($m.sid)"; if ($osid -notmatch '^[0-9a-f-]{36}$') { $osid = '' }
        $body = @{ kind = 'skola'; name = "$($m.subject) $($m.base)"; title = "$($m.title)"; subject = "$($m.subject)"; file = "$($m.file)"; text = $review; source = "$($m.source)"
                   owner = @{ sid = $osid; title = ''; cwd = "$($m.cwd)" } }
        if (-not (Test-Path -LiteralPath "$($d.FullName)\output.pdf")) { $body.pdf_failed = if ($m.pdf_error) { "$($m.pdf_error)" } else { 'no PDF copy' } }
        $r = Api 'Post' '/api/pc/docs/upload' $body
        if (Test-Path -LiteralPath "$($d.FullName)\output.pdf") {
            $bytes = [IO.File]::ReadAllBytes("$($d.FullName)\output.pdf")
            Invoke-WebRequest -Uri "$base/api/pc/docs/$($r.slug)/pdf" -Method Post -Headers $headers -Body $bytes -ContentType 'application/pdf' -TimeoutSec 180 -UseBasicParsing | Out-Null
        }
        New-Item -ItemType Directory -Force $sent | Out-Null
        Move-Item -LiteralPath $d.FullName -Destination (Join-Path $sent ((Get-Date -Format 'yyyyMMdd-HHmmss-') + 'skola-' + $d.Name)) -Force
        Write-Log "school output sent to phone: $($m.subject) / $($m.base) ($($r.slug))"
    }
}

# ------------------------------------------------------------------ to-do list + session mailbox (stage 11d)

function Get-SessionSnap {
    # The newest snapshot mc_sessions.py wrote (Send-Sessions); $null when it is stale (then nothing is decided from it).
    $f = Join-Path $env:TEMP 'mc-sessions.json'
    if (-not (Test-Path -LiteralPath $f)) { return $null }
    if (((Get-Date) - (Get-Item -LiteralPath $f).LastWriteTime).TotalSeconds -gt 90) { return $null }
    try { ReadJson $f } catch { $null }
}

function Test-Waiter($dir) {
    # True when an mc-wait.ps1 of this session is running (its .waiter file names a live PowerShell with the same start time).
    $f = Join-Path $dir '.waiter'
    if (-not (Test-Path -LiteralPath $f)) { return $false }
    try {
        $w = Get-Content -LiteralPath $f -Raw -Encoding UTF8 | ConvertFrom-Json
        $p = Get-Process -Id ([int]$w.pid) -ErrorAction Stop
        if ($p.ProcessName -notmatch '^(powershell|pwsh)$') { return $false }
        return ([math]::Abs(($p.StartTime.ToUniversalTime() - [datetime]::Parse($w.started).ToUniversalTime()).TotalSeconds) -le 5)
    } catch { return $false }
}

$script:delivered = @{}      # to-do id -> "state|detail" last reported to the Pi
function Report-Delivery($id, $state, $detail) {
    if (-not $id -or $script:delivered[$id] -eq "$state|$detail") { return }
    try { Api 'Post' '/api/pc/todos/delivery' @{ id = $id; state = $state; detail = $detail } | Out-Null; $script:delivered[$id] = "$state|$detail" }
    catch { Write-Log "delivery report: $($_.Exception.Message)" }
}

function Write-MailboxFile($sid, $name, $body) {
    # Hidden temp name first, then rename: mc-wait.ps1 never reads a half-written file.
    $dir = "$Hub\to-session\$sid"
    New-Item -ItemType Directory -Force $dir | Out-Null
    $tmp = Join-Path $dir ".tmp-$name"
    [IO.File]::WriteAllText($tmp, $body, $utf8)
    $final = Join-Path $dir $name
    Move-Item -LiteralPath $tmp -Destination $final -Force
    $final
}

function Sync-Crashes {
    # App crash reports saved on the Pi -> D:\ai-hub\files\mc-crashes\<name>.txt; the Pi copy is deleted only after the file is written.
    $c = Api 'Get' '/api/pc/crashes'
    $got = @()
    foreach ($x in @($c.crashes)) {
        if (-not $x -or "$($x.name)" -notmatch '^[0-9]{8}-[0-9]{6}-[0-9]+\.txt$') { continue }
        $dir = "$Hub\files\mc-crashes"
        New-Item -ItemType Directory -Force $dir | Out-Null
        [IO.File]::WriteAllText("$dir\$($x.name)", "$($x.text)", $utf8)
        $got += "$($x.name)"
        Write-Log "app crash report saved: $($x.name)"
    }
    if ($got.Count) { Api 'Post' '/api/pc/crashes/ack' @{ names = $got } | Out-Null }
}

function Sync-Todos {
    $open = "$Hub\todo\open"; $doneDir = "$Hub\todo\done"
    New-Item -ItemType Directory -Force $open, $doneDir | Out-Null
    $snap = Get-SessionSnap
    # 1) new items -> the Pi (idempotent there, so a lost marker only repeats the upload)
    foreach ($f in Get-ChildItem "$open\*.json" -ErrorAction SilentlyContinue) {
        $id = $f.BaseName
        if ($id -notmatch '^\d{8}-\d{6}-[a-z0-9]{4}$' -or (Test-Path -LiteralPath "$open\$id.uploaded")) { continue }
        $t = ReadJson $f.FullName
        $sid = "$($t.session.sid)"
        if ($sid -and $sid -notmatch '^[0-9a-f-]{36}$') { $sid = '' }
        $stitle = ''
        if ($snap -and $sid) { $s = @($snap.sessions) | Where-Object { $_.id -eq $sid } | Select-Object -First 1; if ($s) { $stitle = "$($s.title)" } }
        $body = @{ id = $id; title = "$($t.title)"; steps = "$($t.steps)"; kind = "$($t.kind)"; project = "$($t.project)"
                   source = "$($t.source)"; created = [double]$t.created; session = @{ sid = $sid; title = $stitle } }
        if ($t.checklist -and (Test-Path -LiteralPath "$open\$id.checklist.md")) {
            $body.checklist = @{ name = "todo-$id.md"; text = [IO.File]::ReadAllText("$open\$id.checklist.md", $utf8) }
        }
        Api 'Post' '/api/pc/todos/upload' $body | Out-Null
        [IO.File]::WriteAllText("$open\$id.uploaded", '', $utf8)
        Write-Log "to-do sent to phone: $id ($($t.title))"
    }
    # 2) results from the phone -> the source session's mailbox
    $c = Api 'Get' '/api/pc/todos/changes'
    $acks = @()
    foreach ($r in @($c.changes)) {
        if (-not $r -or "$($r.id)" -notmatch '^\d{8}-\d{6}-[a-z0-9]{4}$') { continue }
        $id = "$($r.id)"
        $dir = "$Hub\files\todo\$id"
        New-Item -ItemType Directory -Force $dir | Out-Null
        $photoPaths = @()
        foreach ($ph in @($r.photos)) {
            if ("$ph" -notmatch '^[0-9a-z-]+-\d+-[a-z0-9]+\.jpg$') { continue }
            if (-not (Test-Path -LiteralPath "$dir\$ph")) {
                Invoke-WebRequest -Uri "$base/api/pc/todos/photo/$id/$ph" -Headers $headers -OutFile "$dir\$ph" -TimeoutSec 60 -UseBasicParsing
            }
            $photoPaths += "$dir\$ph"
        }
        $sid = "$($r.session.sid)"; if ($sid -notmatch '^[0-9a-f-]{36}$') { $sid = '' }
        $when = [DateTimeOffset]::FromUnixTimeSeconds([long]$r.closed_at).LocalDateTime.ToString('yyyy-MM-dd HH:mm')
        $what = if ($r.status -eq 'done') { 'done' } else { "marked 'can't do it'" }
        $lines = New-Object System.Collections.Generic.List[string]
        $lines.Add("# To-do result: $($r.title)")
        $extra = if ($r.summary -and $r.summary -notin @('Done', "Can't do it")) { " ($($r.summary))" } else { '' }
        $lines.Add("Result: $what$extra   Closed: $when   To-do id: $id")
        if ($r.note) { $lines.Add(''); $lines.Add("Filip's note:"); $lines.Add("$($r.note)") }
        if ($photoPaths.Count) { $lines.Add(''); $lines.Add('Photos from Filip:'); foreach ($pp in $photoPaths) { $lines.Add("- $pp") } }
        if ($r.checklist) {
            $lines.Add(''); $lines.Add("Phone-test checklist results: $Hub\files\checklists\$($r.checklist)\results.md (screenshots in that folder)")
        }
        $details = ($lines -join "`n") + "`n"
        [IO.File]::WriteAllText("$dir\result.md", $details, $utf8)
        $subject = "Mission Control: to-do '$($r.title)' is $what" + $(if ($r.summary -and $r.status -eq 'done' -and $r.summary -ne 'Done') { " ($($r.summary))" } else { '' }) + '.'
        $msg = "$subject`nFrom: filip (phone)   Date: $when`nA to-do result is information, not approval for anything else.`n`n$details`nDetails: $dir\result.md`n"
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        if ($sid) {
            Write-MailboxFile $sid "$stamp-todo-$id.md" $msg | Out-Null
            Write-Log "to-do $id -> mailbox of $sid ($($r.status))"
            Report-Delivery $id 'queued' 'in the session mailbox'
        } else {
            Write-InboxMessage "todo-$id" ("# To-do result: $($r.title)`nFrom: filip   To: claude   Date: $when`n## Task`n$subject`n`n$details## Files`n$dir\result.md`n## Done when`nClaude has read it.`n") | Out-Null
            Write-Log "to-do $id -> inbox (no source session)"
            Report-Delivery $id 'inbox' 'no source session: saved to the Claude inbox'
        }
        # the item file moves to done\ with the result
        foreach ($suffix in '.json', '.checklist.md') {
            if (Test-Path -LiteralPath "$open\$id$suffix") { Move-Item -LiteralPath "$open\$id$suffix" -Destination "$doneDir\$id$suffix" -Force }
        }
        Remove-Item -LiteralPath "$open\$id.uploaded" -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath "$doneDir\$id.json") {
            try {
                $o = ReadJson "$doneDir\$id.json"
                $o | Add-Member -NotePropertyName result -NotePropertyValue ([pscustomobject]@{ status = "$($r.status)"; summary = "$($r.summary)"; note = "$($r.note)"; closed = $when; photos = $photoPaths }) -Force
                [IO.File]::WriteAllText("$doneDir\$id.json", (ConvertTo-Json $o -Depth 6), $utf8)
            } catch { Write-Log "to-do $id result write: $($_.Exception.Message)" }
        }
        $acks += $id
    }
    if ($acks.Count) { Api 'Post' '/api/pc/todos/ack' @{ ids = $acks } | Out-Null }
}

$script:typeRetryAt = @{}    # mailbox file -> earliest next typing attempt
function Process-Mailboxes {
    # Files in to-session\<sid>\ that no waiter takes: type them into the Desktop session, or fall back to the inbox.
    $root = "$Hub\to-session"
    if (-not (Test-Path -LiteralPath $root)) { return }
    $snap = Get-SessionSnap
    foreach ($dir in Get-ChildItem $root -Directory -ErrorAction SilentlyContinue) {
        $sid = $dir.Name
        if ($sid -notmatch '^[0-9a-f-]{36}$') { continue }
        $files = @(Get-ChildItem -LiteralPath $dir.FullName -Filter '*.md' -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike '.*' } | Sort-Object Name)
        if (-not $files.Count) { continue }
        $waiting = Test-Waiter $dir.FullName
        foreach ($f in $files) {
            $tid = if ($f.Name -match '-todo-(\d{8}-\d{6}-[a-z0-9]{4})\.md$') { $Matches[1] } else { '' }
            if ($waiting) { Report-Delivery $tid 'waiter' 'a waiting session reads it at once'; continue }
            if (-not $snap) { continue }                      # no fresh view of the sessions: decide next round
            $s = @($snap.sessions) | Where-Object { $_.id -eq $sid } | Select-Object -First 1
            $done = Join-Path $dir.FullName 'done'
            if (-not $s) {
                # the session is not running: the Claude inbox is read by the next boss session
                $text = [IO.File]::ReadAllText($f.FullName, $utf8)
                Write-InboxMessage "mailbox-$($f.BaseName)" ("# Message from Filip's phone (session $sid has ended)`nFrom: filip   To: claude   Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm')`n## Task`n$text`n## Files`n$($f.FullName)`n## Done when`nClaude has read it.`n") | Out-Null
                New-Item -ItemType Directory -Force $done | Out-Null
                Move-Item -LiteralPath $f.FullName -Destination (Join-Path $done $f.Name) -Force
                Write-Log "mailbox $($f.Name): session not running, copied to the inbox"
                Report-Delivery $tid 'inbox' 'session not running: saved to the Claude inbox'
                continue
            }
            if ($s.kind -ne 'desktop' -or -not $s.local) { Report-Delivery $tid 'mailbox' 'in the mailbox (nobody waiting; this session cannot be typed into)'; continue }
            if ($s.state -ne 'idle') { Report-Delivery $tid 'waiting' "the session is $($s.state); it reads the mailbox at its next turn"; continue }
            if (Get-Process LogonUI -ErrorAction SilentlyContinue) { Report-Delivery $tid 'waiting' 'waiting for PC: it is locked'; continue }
            if ($script:typeRetryAt[$f.FullName] -and (Get-Date) -lt $script:typeRetryAt[$f.FullName]) { continue }
            # Typing fallback. The file moves to done\ first, so the path in the typed line stays valid.
            New-Item -ItemType Directory -Force $done | Out-Null
            $moved = Join-Path $done $f.Name
            Move-Item -LiteralPath $f.FullName -Destination $moved -Force
            $first = ([IO.File]::ReadAllText($moved, $utf8) -split "`r?`n")[0]
            if ($first -notmatch '^Mission Control:') { $first = "Mission Control: a message from Filip's phone." }
            $line = "$first Details: $moved"
            $tmp = Join-Path $env:TEMP "mc-type-mailbox-$($f.BaseName).txt"
            [IO.File]::WriteAllText($tmp, $line, $utf8)
            try {
                $out = & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass `
                    -File (Join-Path $here 'mc-type.ps1') -Local "$($s.local)" -Title "$($s.title)" -TextFile $tmp 2>&1 | Out-String
                $code = $LASTEXITCODE
            } finally { Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue }
            $why = $script:typeCodes[[int]$code]; if (-not $why) { $why = "error $code" }
            Write-Log "mailbox $($f.Name) typed into '$($s.title)': $why $($out.Trim())"
            if ($code -eq 0) { Report-Delivery $tid 'typed' 'typed into the session'; continue }
            Move-Item -LiteralPath $moved -Destination $f.FullName -Force          # not delivered: back into the mailbox
            $script:typeRetryAt[$f.FullName] = (Get-Date).AddSeconds($(if ($code -eq 3) { 15 } else { 60 }))
            Report-Delivery $tid 'waiting' $(if ($code -eq 3) { 'waiting for PC: it is locked' } else { "typing failed ($why); retrying" })
        }
    }
}

# ------------------------------------------------------------------ starting work from the phone (stage 11c)

function Get-PyJson($script, $arg, $envItem) {
    $py = Get-PythonExe
    if (-not $py) { throw 'python not found on the PC' }
    if ($null -ne $envItem) { $env:MC_ITEM = ConvertTo-Json $envItem -Compress -Depth 5 }
    try { (& $py -I (Join-Path $here $script) $arg 2>$null | Out-String) | ConvertFrom-Json } finally { Remove-Item Env:MC_ITEM -ErrorAction SilentlyContinue }
}

# The real sub-folders of D:\projekty and D:\Skola for the phone's "new session" sheet.
$script:nextFolders = Get-Date
function Send-Folders {
    $f = Get-PyJson 'mc_launch.py' 'folders' $null
    Api 'Post' '/api/pc/folders' @{ projects = @($f.projects); skola = @($f.skola) } | Out-Null
}

# A photo / PDF of an assignment: download the files from the Pi, save them under D:\Skola\<subject>\<new task>\podklady\,
# tell the Pi (which then asks the boss session to start the Czech session). Always acked: a failure is reported, not retried.
function Save-SkolaTask($it) {
    $tmp = Join-Path $env:TEMP "mc-skola-$($it.key)"
    try {
        New-Item -ItemType Directory -Force $tmp | Out-Null
        $files = @(); $i = 0
        foreach ($f in @($it.files)) {
            $i++
            if ("$($f.id)" -notmatch '^[0-9a-f]{20}$') { throw 'bad file id' }
            $p = Join-Path $tmp ("f$i.bin")
            Invoke-WebRequest -Uri "$base/api/pc/launch/file/$($f.id)" -Headers $headers -OutFile $p -TimeoutSec 120 -UseBasicParsing
            $files += @{ path = $p; name = "$($f.name)" }
        }
        $r = Get-PyJson 'mc_launch.py' 'skola-save' @{ key = "$($it.key)"; subject = "$($it.subject)"; files = $files }
    } catch { $r = [pscustomobject]@{ ok = $false; detail = "PC could not save the files: $($_.Exception.Message)" } }
    finally { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Log "skola task $($it.key) ($($it.subject)): ok=$($r.ok) $($r.task) $($r.detail)"
    Api 'Post' '/api/pc/launch/saved' @{ key = "$($it.key)"; ok = [bool]$r.ok; detail = "$($r.detail)"; folder = "$($r.folder)"; task = "$($r.task)"; saved = @($r.saved) } | Out-Null
}

# ------------------------------------------------------------------ main loop

if ($Test) {
    ConvertTo-Json (Get-Usage) -Depth 6
    ConvertTo-Json (Get-PcStats)
    ConvertTo-Json @{ parked = Get-Parked; logs = @((Tail-Logs).Keys); handoff_chars = (Handoff-Summary).Length } -Depth 4
    exit
}
if ($TestLocalAi) { Get-LocalAiJson; exit }
if ($TestBitwarden) { Open-Bitwarden -DryRun | ConvertTo-Json -Compress; exit }
if ($TestRestart) { Restart-ClaudeApp -DryRun | ConvertTo-Json -Compress; exit }
$mutex = New-Object System.Threading.Mutex($false, 'Global\mission-control-mc-pc')
if (-not $mutex.WaitOne(0)) { exit }   # already running

$lastError = $null
$nextReport = Get-Date
$nextUsage = Get-Date
$usage = $null
Write-Log 'started'

while ($true) {
    try {
        $reply = Api 'Get' '/api/pc/command'
        if ($lastError) { Write-Log 'connected again'; $lastError = $null }
        $done = @()
        foreach ($it in @($reply.inbox)) {
            if (-not $it) { continue }
            try { Handle-Item $it; $done += $it.key } catch { if ($_.Exception.Message -notlike 'waiting:*') { Write-Log "inbox item failed: $($_.Exception.Message)" } }
        }
        if ($done.Count) { Api 'Post' '/api/pc/ack' @{ keys = $done } | Out-Null; $nextUsage = Get-Date }
        if ($reply.digest) { try { Send-Digest } catch { Write-Log "digest: $($_.Exception.Message)" } }
        try { Send-Sessions "$($reply.watch)" } catch { Write-Log "sessions: $($_.Exception.Message)" }
        try { Check-ModeJob } catch { Write-Log "pc-mode job: $($_.Exception.Message)" }
        if ($reply.ai_watch -and (Get-Date) -ge $script:nextLocalAi) {
            try { Send-LocalAi } catch { Write-Log "localai: $($_.Exception.Message)" }
            $script:nextLocalAi = (Get-Date).AddSeconds(4)
        }
        try { Send-CardShots } catch { Write-Log "appcard screenshot: $($_.Exception.Message)" }
        if ((Get-Date) -ge $script:nextFolders) { try { Send-Folders; $script:nextFolders = (Get-Date).AddMinutes(5) } catch { Write-Log "folders: $($_.Exception.Message)"; $script:nextFolders = (Get-Date).AddMinutes(1) } }
        try { Sync-Plans } catch { Write-Log "plans sync: $($_.Exception.Message)" }
        if ((Get-Date) -ge $nextUsage) { $usage = Get-Usage; $nextUsage = (Get-Date).AddMinutes(10); $nextReport = Get-Date }
        if ((Get-Date) -ge $nextReport) {
            Api 'Post' '/api/pc/report' @{ logs = Tail-Logs; handoff = Handoff-Summary; approvals = (Pending-Approvals)
                                           parked = Get-Parked; usage = $usage; stats = (Get-PcStats); health = (Get-HealthReport -WithHelpers:($null -ne $usage)); questions = (Get-OpenQuestions); pcmode = (Get-PcModeReport) } | Out-Null
            $usage = $null   # numbers are sent once per refresh; mc-pi keeps the last ones
            try { Sync-Docs } catch { Write-Log "docs sync: $($_.Exception.Message)" }
            try { Sync-Skola } catch { Write-Log "skola sync: $($_.Exception.Message)" }
            try { Sync-Todos } catch { Write-Log "todo sync: $($_.Exception.Message)" }
            try { Sync-Crashes } catch { Write-Log "crash sync: $($_.Exception.Message)" }
            try { Process-Mailboxes } catch { Write-Log "mailbox: $($_.Exception.Message)" }
            $nextReport = (Get-Date).AddSeconds(15)
        }
        if ($reply.screenshot) { try { Send-Screenshot } catch { Write-Log "screenshot failed: $($_.Exception.Message)" } }
        if ($reply.cmd -eq 'sleep') {
            Write-Log 'sleep requested from the phone: sleeping'
            Add-Type -AssemblyName System.Windows.Forms
            [void][System.Windows.Forms.Application]::SetSuspendState([System.Windows.Forms.PowerState]::Suspend, $false, $false)
            Write-Log 'resumed'
            $nextUsage = Get-Date
        }
    } catch {
        $msg = $_.Exception.Message
        if ($_.ErrorDetails.Message) { $msg += ' ' + $_.ErrorDetails.Message.Substring(0, [Math]::Min(300, $_.ErrorDetails.Message.Length)) }
        if ($msg -ne $lastError) { Write-Log "error: $msg"; $lastError = $msg }
    }
    Start-Sleep -Milliseconds $(if ($reply.watch -or $reply.ai_watch -or $script:modeJob) { 1000 } else { 4000 })   # faster while the phone has a session or the Local AI card open
}
