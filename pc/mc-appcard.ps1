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
# the smallest ancestor that also holds exactly one "Deny", and it must be named "Permission request…".
# Only those two names are ever invoked, never
# "Always allow". Right before the click everything is checked again (same card name, same session URL, still the
# only pending card, no other card emitted for the session since the first check). The window is brought to the
# front, the button is Invoked; if the log does not confirm within 4 s, a real mouse click follows, but only when
# the element under the button's centre is that button. The click counts only when main.log logs
# "Received permission response" for that id.
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
# Every card emitted for this session after this point is a reason to refuse (re-checked right before the click).
$off0 = (Invoke-Helper @('offset')).offset

if (Get-Process LogonUI -ErrorAction SilentlyContinue) { $base.reason = 'PC locked'; Out-Result $base 3 }

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$AE = [Windows.Automation.AutomationElement]
$CT = [Windows.Automation.ControlType]
Add-Type -Namespace McAppCard -Name U32 -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
[DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
[DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
[DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
public struct POINT { public int X; public int Y; }
'@
function Cond($prop, $val) { New-Object Windows.Automation.PropertyCondition($prop, $val) }
function Find-ClaudeWindow {
    foreach ($p in Get-Process Claude -ErrorAction SilentlyContinue | Where-Object MainWindowHandle -ne 0) {
        $w = $AE::RootElement.FindFirst('Children', (Cond $AE::ProcessIdProperty $p.Id))
        if ($w) { return $w }
    }
    $null
}
# The session's web document: bound by its URL (UIA Value of the RootWebArea is
# https://claude.ai/epitaxy/<local_id>), and its name must be "<title> - Claude Code". Exactly one may match each.
function Get-DocUrl($d) {
    try { "$($d.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern).Current.Value)" } catch { '' }
}
function Get-SessionDoc($w, [string]$local, [string]$title) {
    $want = "$title - Claude Code"
    $byUrl = @(); $byName = 0; $open = @()
    foreach ($d in $w.FindAll('Descendants', (Cond $AE::AutomationIdProperty 'RootWebArea'))) {
        $n = $d.Current.Name
        if ($n -like '* - Claude Code') { $open += $n }
        if ($n -eq $want) { $byName++ }
        if ((Get-DocUrl $d) -match "/epitaxy/$([regex]::Escape($local))(?:[/?#]|$)") { $byUrl += $d }
    }
    $r = @{ doc = $null; open = ($open -join ' | '); why = '' }
    if ($byUrl.Count -eq 0) { $r.why = 'session not open'; return $r }
    if ($byUrl.Count -gt 1) { $r.why = "$($byUrl.Count) documents show that session"; return $r }
    if ($byName -gt 1) { $r.why = "$byName documents are named '$want'"; return $r }
    if ($byUrl[0].Current.Name -ne $want) { $r.why = "open document is '$($byUrl[0].Current.Name)', expected '$want'"; return $r }
    $r.doc = $byUrl[0]
    $r
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
$w = $null; $s = @{ doc = $null; open = ''; why = '' }
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    $w = Find-ClaudeWindow
    if (-not $w) { continue }
    $s = Get-SessionDoc $w $card.session $card.title
    if ($s.doc) { break }
}
if (-not $w) { $base.reason = 'Claude window not found'; Out-Result $base 6 }
if (-not $s.doc) { $base.reason = "wrong session open ($($s.why)): $($s.open)"; Out-Result $base 7 }
# In front before the search: twice a card was missing from the UIA tree of a background window.
try { [void][McAppCard.U32]::SetForegroundWindow([IntPtr]$w.Current.NativeWindowHandle) } catch { }

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
$base.cardName = "$($box.Current.Name)"
$base.cardText = @(Get-Texts $box)
# App 5.11492.5: the card is a Group named "Permission request: <what> “<detail>”" holding Deny and Allow once.
if ($base.cardName -notlike 'Permission request*') {
    $base.reason = "the buttons are not inside a 'Permission request' card (found '$($base.cardName)')"
    if ($DumpTree) { Write-Tree $box $DumpTree; $base.dump = $DumpTree }
    Out-Result $base 8
}
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
$off = (Invoke-Helper @('offset')).offset
# Re-check right before the click: the card on screen is still this request's card (same name, fits the tool),
# the document is still this session, the request is still the only pending card there and no other card
# was emitted for the session since the first check.
try {
    $nameNow = "$($box.Current.Name)"
    $targetNow = "$($target.Current.Name)"
    $urlNow = Get-DocUrl $s.doc
} catch { $base.reason = 'card went away before the click'; Out-Result $base 8 }
if ($targetNow -ne $(if ($Decision -eq 'allow') { $allowName } else { $denyName })) { $base.reason = 'button name changed'; Out-Result $base 8 }
if ($nameNow -ne $base.cardName) { $base.reason = 'card changed before the click'; Out-Result $base 8 }
if ($urlNow -notmatch "/epitaxy/$([regex]::Escape($card.session))(?:[/?#]|$)") { $base.reason = 'session changed before the click'; Out-Result $base 7 }
$ra = @('check', $Answer, '--since', "$off0", '--card-name', $nameNow)
if ($ExpectTitle) { $ra += @('--expect-title', $ExpectTitle) }
if ($Tool) { $ra += @('--tool', $Tool) }
$re = Invoke-Helper $ra
if (-not $re.ok) { $base.reason = "re-check before the click: $($re.reason)"; Out-Result $base 4 }
# Window in front first: live, an Invoke on "Allow once" of a background window was ignored by the app (Deny was not).
try { [void][McAppCard.U32]::SetForegroundWindow([IntPtr]$w.Current.NativeWindowHandle) } catch { }
Start-Sleep -Milliseconds 700
$base.buttonEnabled = [bool]$target.Current.IsEnabled
if (-not $base.buttonEnabled) { $base.reason = "'$targetNow' button is disabled"; Out-Result $base 8 }
$base.method = 'invoke'
$target.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
$conf = Invoke-Helper @('confirm', $Answer, '--from', "$off", '--timeout', '4')
if (-not $conf.ok -and $conf.reason -ne 'card aborted') {
    # Fallback: a real mouse click on the button, only if the element under its centre is that very button.
    $r = $target.Current.BoundingRectangle
    $x = [int]($r.X + $r.Width / 2); $y = [int]($r.Y + $r.Height / 2)
    $hit = $null
    try { $hit = $AE::FromPoint((New-Object Windows.Point($x, $y))) } catch { }
    $same = $hit -and ([Windows.Automation.Automation]::Compare($hit, $target) -or
                       ($hit.Current.ControlType -eq $CT::Text -and [Windows.Automation.Automation]::Compare([Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($hit), $target)))
    if (-not $same) { $base.reason = "Invoke not confirmed and the button is not on top at ($x,$y) for a mouse click"; Out-Result $base 9 }
    $re = Invoke-Helper $ra                                # still the same single pending card?
    if (-not $re.ok) { $base.reason = "re-check before the mouse click: $($re.reason)"; Out-Result $base 4 }
    $base.method = 'mouse'
    $old = New-Object McAppCard.U32+POINT
    [void][McAppCard.U32]::GetCursorPos([ref]$old)
    [void][McAppCard.U32]::SetCursorPos($x, $y)
    Start-Sleep -Milliseconds 120
    [McAppCard.U32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)   # left down
    Start-Sleep -Milliseconds 60
    [McAppCard.U32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)   # left up
    Start-Sleep -Milliseconds 150
    [void][McAppCard.U32]::SetCursorPos($old.X, $old.Y)
    $conf = Invoke-Helper @('confirm', $Answer, '--from', "$off", '--timeout', '10')
}
if (-not $conf.ok) { $base.reason = "click not confirmed: $($conf.reason)"; Out-Result $base 9 }
$want = if ($Decision -eq 'allow') { 'once' } else { 'deny' }
$base.confirmedBy = $conf.line
if ($conf.decision -ne $want) { $base.reason = "log says '$($conf.decision)', expected '$want'"; Out-Result $base 9 }
$base.ok = $true
Out-Result $base 0
