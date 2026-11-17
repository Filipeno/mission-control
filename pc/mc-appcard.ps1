# mc-appcard: answers one of the Claude desktop app's own approval cards (Allow once / Deny) by clicking it
# through UI Automation, the only way the app accepts an Allow on its card-only asks. Stage 11a-1 spike.
#
#   mc-appcard.ps1 -List
#   mc-appcard.ps1 -Answer <requestId> -Decision allow|deny [-ExpectTitle <t>] [-Tool <t>] [-DumpTree <file>]
#   mc-appcard.ps1 -Answer <requestId> -DumpTree <file>            (dump only, no click)
#   mc-appcard.ps1 -WaitNext [-Tool <t>] [-WaitTimeout 300] [-Decision allow|deny ...]
#                                                                  (waits for the next new card; answers it if -Decision)
#
# Safety: pc/mc_appcard.py first checks the log (card still pending, title matches -ExpectTitle, tool matches -Tool,
# exactly one Allow/Deny card pending in that session). Then the session is opened with the app's claude:// link and
# the open session must be the right one. Inside it there must be exactly one button named "Allow once"; the card is
# the smallest ancestor that also holds exactly one "Deny". Only those two names are ever invoked, never
# "Always allow". The click counts only when main.log logs "Received permission response" for that id within 10 s.
# Exit codes: 0 done, 2 bad arguments, 3 PC locked, 4 refused by the log check, 6 window/session not found,
#             7 wrong session open, 8 card not found or ambiguous, 9 click not confirmed by the log, 10 no new card.
param(
    [switch]$List,
    [string]$Answer = '',
    [ValidateSet('', 'allow', 'deny')][string]$Decision = '',
    [string]$ExpectTitle = '',
    [string]$Tool = '',
    [string]$DumpTree = '',
    [switch]$WaitNext,
    [int]$WaitTimeout = 300,
    [string]$LogDir = '',          # tests only: a fixture log folder instead of %LOCALAPPDATA%\Claude\Logs
    [string]$Titles = ''           # tests only: JSON {local_id: title}
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$helper = Join-Path $here 'mc_appcard.py'
$py = (Get-Command python -ErrorAction SilentlyContinue).Source

function Out-Result($obj, [int]$code) {
    $obj | ConvertTo-Json -Compress -Depth 6 | Write-Output
    exit $code
}
function Invoke-Helper([string[]]$a) {
    if ($LogDir) { $a += @('--log-dir', $LogDir) }
    if ($Titles) { $a += @('--titles', $Titles) }
    $raw = & $py -I $helper @a
    if ($LASTEXITCODE -ne 0 -or -not $raw) { throw "mc_appcard.py $($a[0]) failed" }
    ($raw -join "`n") | ConvertFrom-Json
}

if (-not $py) { Out-Result @{ ok = $false; reason = 'python not found' } 2 }
if ($List) { Invoke-Helper @('list') | ConvertTo-Json -Compress -Depth 6; exit 0 }

if ($WaitNext) {
    $off = (Invoke-Helper @('offset')).offset
    $wa = @('wait', '--from', "$off", '--timeout', "$WaitTimeout")
    if ($Tool) { $wa += @('--tool', $Tool) }
    $w = Invoke-Helper $wa
    if (-not $w.ok) { Out-Result @{ ok = $false; reason = $w.reason } 10 }
    if (-not $Decision -and -not $DumpTree) { Out-Result @{ ok = $true; card = $w.card } 0 }
    $Answer = $w.card.id
    Start-Sleep -Milliseconds 800                          # let the card render
}

if ($Answer -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') {
    Out-Result @{ ok = $false; reason = 'need -List, -WaitNext or -Answer <requestId>' } 2
}
if (-not $Decision -and -not $DumpTree) { Out-Result @{ ok = $false; reason = 'need -Decision allow|deny or -DumpTree' } 2 }

# 1. The log must say this card is still open and may be answered.
$ca = @('check', $Answer)
if ($ExpectTitle) { $ca += @('--expect-title', $ExpectTitle) }
if ($Tool) { $ca += @('--tool', $Tool) }
$chk = Invoke-Helper $ca
$card = $chk.card
$base = [ordered]@{ ok = $false; requestId = $Answer; tool = "$($card.tool)"; session = "$($card.session)";
                    title = "$($card.title)"; decision = $Decision }
if (-not $chk.ok) { $base.reason = $chk.reason; Out-Result $base 4 }
if ($LogDir) { $base.reason = 'log check passed (fixture log: no click)'; $base.ok = $true; Out-Result $base 0 }

if (Get-Process LogonUI -ErrorAction SilentlyContinue) { $base.reason = 'PC locked'; Out-Result $base 3 }

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$AE = [Windows.Automation.AutomationElement]
$CT = [Windows.Automation.ControlType]
function Cond($prop, $val) { New-Object Windows.Automation.PropertyCondition($prop, $val) }
function Find-ClaudeWindow {
    foreach ($p in Get-Process Claude -ErrorAction SilentlyContinue | Where-Object MainWindowHandle -ne 0) {
        $w = $AE::RootElement.FindFirst('Children', (Cond $AE::ProcessIdProperty $p.Id))
        if ($w) { return $w }
    }
    $null
}
function Get-SessionDoc($w, [string]$title) {
    $want = "$title - Claude Code"
    $named = @()
    foreach ($d in $w.FindAll('Descendants', (Cond $AE::AutomationIdProperty 'RootWebArea'))) {
        $n = $d.Current.Name
        if ($n -like '* - Claude Code') { $named += $n }
        if ($n -eq $want) { return @{ doc = $d; open = $n } }
    }
    @{ doc = $null; open = ($named -join ' | ') }
}
function Get-Buttons($root, [string]$name) {
    $c = New-Object Windows.Automation.AndCondition((Cond $AE::ControlTypeProperty $CT::Button), (Cond $AE::NameProperty $name))
    @($root.FindAll('Descendants', $c))
}
function Write-Tree($el, [string]$path) {
    $walker = [Windows.Automation.TreeWalker]::ControlViewWalker
    $sb = New-Object Text.StringBuilder
    $count = 0
    function Walk($e, [int]$depth) {
        if ($script:count -ge 6000 -or $depth -gt 80) { return }
        $script:count++
        $c = $e.Current
        $pat = @()
        foreach ($p in $e.GetSupportedPatterns()) { $pat += ($p.ProgrammaticName -replace 'PatternIdentifiers.Pattern', '') }
        [void]$sb.AppendLine(('{0}[{1}] name="{2}" id="{3}" class="{4}" patterns={5}' -f ('  ' * $depth),
            ($c.ControlType.ProgrammaticName -replace 'ControlType.', ''), $c.Name, $c.AutomationId, $c.ClassName, ($pat -join ',')))
        $ch = $walker.GetFirstChild($e)
        while ($ch) { Walk $ch ($depth + 1); $ch = $walker.GetNextSibling($ch) }
    }
    $script:count = 0
    Walk $el 0
    [IO.File]::WriteAllText($path, $sb.ToString(), [Text.Encoding]::UTF8)
}
function Get-Texts($el) {
    $t = @()
    foreach ($e in $el.FindAll('Descendants', [Windows.Automation.Condition]::TrueCondition)) {
        $n = $e.Current.Name
        if ($n -and $t -notcontains $n) { $t += $n }
    }
    $t
}

# 2. Open the session and wait until the window shows it.
Start-Process "claude://claude.ai/epitaxy/$($card.session)"
$w = $null; $s = @{ doc = $null; open = '' }
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    $w = Find-ClaudeWindow
    if (-not $w) { continue }
    $s = Get-SessionDoc $w $card.title
    if ($s.doc) { break }
}
if (-not $w) { $base.reason = 'Claude window not found'; Out-Result $base 6 }
if (-not $s.doc) { $base.reason = "wrong session open: $($s.open)"; Out-Result $base 7 }

# 3. Find exactly one card in that session: one "Allow once", and its smallest ancestor holding exactly one "Deny".
$allowName = 'Allow once'; $denyName = 'Deny'
$allow = @(); $box = $null; $deny = $null
for ($i = 0; $i -lt 10 -and -not $box; $i++) {
    if ($i) { Start-Sleep -Milliseconds 500 }
    $allow = Get-Buttons $s.doc $allowName
    if ($allow.Count -ne 1) { continue }
    $walker = [Windows.Automation.TreeWalker]::ControlViewWalker
    $p = $walker.GetParent($allow[0])
    for ($up = 0; $p -and $up -lt 8; $up++) {
        $d = Get-Buttons $p $denyName
        if ($d.Count -eq 1) { $box = $p; $deny = $d[0]; break }
        if ($d.Count -gt 1) { break }
        $p = $walker.GetParent($p)
    }
}
if ($allow.Count -ne 1 -or -not $box) {
    $base.reason = "card not found: $($allow.Count) '$allowName' button(s) in the session" + $(if ($allow.Count -eq 1) { ", no single '$denyName' next to it" } else { '' })
    # What the whole window shows instead: every element whose name mentions allow/deny (any control type).
    $seen = foreach ($e in $w.FindAll('Descendants', [Windows.Automation.Condition]::TrueCondition)) {
        $n = $e.Current.Name
        if ($n -and $n.Length -lt 120 -and $n -match 'allow|deny') { "$($e.Current.ControlType.ProgrammaticName -replace 'ControlType.', ''): $n" }
    }
    $base.seen = @($seen | Select-Object -Unique -First 30)
    if ($DumpTree) { Write-Tree $s.doc $DumpTree; $base.dump = $DumpTree }
    Out-Result $base 8
}
$base.cardText = @(Get-Texts $box)
$base.alwaysAllowOffered = (Get-Buttons $box 'Always allow').Count -gt 0
if ($DumpTree) {
    $walker = [Windows.Automation.TreeWalker]::ControlViewWalker
    $ctx = $box
    for ($k = 0; $k -lt 2; $k++) { $up = $walker.GetParent($ctx); if ($up) { $ctx = $up } }   # a little context around the card
    Write-Tree $ctx $DumpTree
    $base.dump = $DumpTree
}
if (-not $Decision) { $base.ok = $true; $base.reason = 'dump only, nothing clicked'; Out-Result $base 0 }

# 4. Click (Invoke) the one button, then 5. wait for the app's own log line.
$target = if ($Decision -eq 'allow') { $allow[0] } else { $deny }
if ($target.Current.Name -ne $(if ($Decision -eq 'allow') { $allowName } else { $denyName })) { $base.reason = 'button name changed'; Out-Result $base 8 }
$off = (Invoke-Helper @('offset')).offset
$target.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
$conf = Invoke-Helper @('confirm', $Answer, '--from', "$off", '--timeout', '10')
if (-not $conf.ok) { $base.reason = "click not confirmed: $($conf.reason)"; Out-Result $base 9 }
$want = if ($Decision -eq 'allow') { 'once' } else { 'deny' }
$base.confirmedBy = $conf.line
if ($conf.decision -ne $want) { $base.reason = "log says '$($conf.decision)', expected '$want'"; Out-Result $base 9 }
$base.ok = $true
Out-Result $base 0
