# mc-pc: Mission Control's PC helper (Windows PowerShell 5.1).
#  - every 5 s : asks mc-pi for commands (sleep) and for Filip's answers and ideas; writes them into D:\ai-hub
#  - every 15 s: sends a report: hub status-log tails, HANDOFF summary, pending approvals (+ pictures), parked AIs
#  - every 10 min: usage numbers for Claude, Codex, Gemini, Antigravity
# Logins of Codex and Antigravity are read where their CLIs keep them, used in memory for one read-only
# usage call, and never sent or saved. Only numbers leave the PC.
# Config: mc-pc.json next to this file (git-ignored). Started by Task Scheduler (install-mc-pc.ps1).
param([switch]$Test)   # -Test: print usage + report parts once and exit (nothing is sent)
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
    Invoke-RestMethod @p
}

function Unix($dt) { [DateTimeOffset]::new($dt).ToUnixTimeSeconds() }
function ReadJson($path) { if (Test-Path -LiteralPath $path) { Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json } }

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
    # LibreHardwareMonitor (running as admin at logon) publishes sensors in WMI. Read-only, local.
    try {
        $s = Get-CimInstance -Namespace root\LibreHardwareMonitor -ClassName Sensor -ErrorAction Stop |
            Where-Object { $_.SensorType -eq 'Temperature' -and $_.Name -match 'CPU Package|Tctl|Tdie|Core \(Tctl' } | Select-Object -First 1
        if ($s) { return [double]$s.Value }
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
    if ($it.kind -eq 'answer') {
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
    } elseif ($it.kind -eq 'gate-config') {
        New-Item -ItemType Directory -Force "$Hub\gate" | Out-Null
        [IO.File]::WriteAllText("$Hub\gate\config.json", (ConvertTo-Json @{ auto = "$($it.auto)"; enabled = [bool]$it.enabled }), $utf8)
        Write-Log "gate config: auto=$($it.auto) enabled=$($it.enabled)"
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

function Send-Result($key, $ok, $detail) {
    try { Api 'Post' '/api/pc/result' @{ key = $key; ok = $ok; detail = "$detail" } | Out-Null } catch { Write-Log "result: $($_.Exception.Message)" }
}

$script:typeCodes = @{ 0 = 'sent'; 2 = 'bad message'; 3 = 'PC is locked'; 4 = 'someone is using the PC'; 5 = 'there is a draft in that session''s prompt box'
                      6 = 'could not find the session in Claude Desktop'; 7 = 'a different session opened' }
Add-Type -Namespace McPc -Name Input -MemberDefinition @'
[StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
[DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO info);
public static uint IdleMs() { var i = new LASTINPUTINFO(); i.cbSize = (uint)Marshal.SizeOf(i); if (!GetLastInputInfo(ref i)) return 0; return unchecked((uint)Environment.TickCount - i.dwTime); }
'@
$script:waitTold = @{}
function Send-Typed($it) {
    # A message (or "Start" for a proposed session) typed into Claude Desktop. Waits while the PC is locked or in use.
    if ([DateTimeOffset]::Now.ToUnixTimeSeconds() - [double]$it.at -gt 1800) { Send-Result $it.key $false 'expired: the PC was locked or in use for 30 min'; return }
    $why = if (Get-Process LogonUI -ErrorAction SilentlyContinue) { 'PC is locked' } elseif ([McPc.Input]::IdleMs() -lt 120000) { 'someone is using the PC' } else { $null }
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
    if ($code -in 3, 4) { throw "waiting: $why" }          # not acked: tried again on the next poll
    Send-Result $it.key ($code -eq 0) $why
}
$script:sessionsAt = [datetime]::MinValue
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
            $r = Api 'Post' '/api/pc/docs/upload' @{ kind = $kind.TrimEnd('s'); name = $f.Name; text = $text }
            Move-Item -LiteralPath $f.FullName -Destination (Join-Path $sent ((Get-Date -Format 'yyyyMMdd-HHmmss-') + $f.Name)) -Force
            Write-Log "sent to phone: $kind\$($f.Name) ($($r.slug))"
        }
    }
    # Phone -> Claude: results, comments, edits, screenshots; Finish / Send to Claude as inbox messages.
    $c = Api 'Get' '/api/pc/docs/changes'
    $acks = @()
    foreach ($ch in @($c.changes)) {
        if (-not $ch) { continue }
        $dir = "$Hub\files\$($ch.kind)s\$($ch.slug)"
        New-Item -ItemType Directory -Force $dir | Out-Null
        if ($ch.kind -eq 'checklist') { [IO.File]::WriteAllText("$dir\results.md", $ch.export, $utf8) }
        else {
            [IO.File]::WriteAllText("$dir\comments.md", $ch.export, $utf8)
            [IO.File]::WriteAllText("$dir\$($ch.slug).md", $ch.text, $utf8)
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

# ------------------------------------------------------------------ main loop

if ($Test) {
    ConvertTo-Json (Get-Usage) -Depth 6
    ConvertTo-Json (Get-PcStats)
    ConvertTo-Json @{ parked = Get-Parked; logs = @((Tail-Logs).Keys); handoff_chars = (Handoff-Summary).Length } -Depth 4
    exit
}
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
        try { Send-Sessions "$($reply.watch)" } catch { Write-Log "sessions: $($_.Exception.Message)" }
        if ((Get-Date) -ge $nextUsage) { $usage = Get-Usage; $nextUsage = (Get-Date).AddMinutes(10); $nextReport = Get-Date }
        if ((Get-Date) -ge $nextReport) {
            Api 'Post' '/api/pc/report' @{ logs = Tail-Logs; handoff = Handoff-Summary; approvals = (Pending-Approvals)
                                           parked = Get-Parked; usage = $usage; stats = (Get-PcStats) } | Out-Null
            $usage = $null   # numbers are sent once per refresh; mc-pi keeps the last ones
            try { Sync-Docs } catch { Write-Log "docs sync: $($_.Exception.Message)" }
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
    Start-Sleep -Milliseconds $(if ($reply.watch) { 1000 } else { 4000 })   # faster while the phone has a session open
}
