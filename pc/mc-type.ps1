# mc-type: puts a message Filip sent from Mission Control into a Claude Desktop session, as if typed at the PC.
# Experimental (Filip's choice, 2026-11-10). Only runs when the PC is unlocked and nobody has touched it
# for -IdleSec seconds. Opens the session through the app's own claude:// link, checks the open session is
# the right one and its prompt box is empty (never mixes with a draft), pastes the text and presses Enter.
# Exit codes: 0 sent, 2 bad arguments, 3 PC locked, 4 PC in use, 5 draft in the prompt box,
#             6 session/prompt box not found, 7 wrong session open.
param([Parameter(Mandatory)][string]$Local, [Parameter(Mandatory)][string]$Title,
      [Parameter(Mandatory)][string]$TextFile, [int]$IdleSec = 120)
$ErrorActionPreference = 'Stop'
if ($Local -notmatch '^local_[0-9a-f-]{36}$' -or -not (Test-Path -LiteralPath $TextFile)) { exit 2 }
$text = [IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8)
if (-not $text.Trim()) { exit 2 }

Add-Type -Namespace McType -Name Native -MemberDefinition @'
[StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
[DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO info);
public static uint IdleMs() { var i = new LASTINPUTINFO(); i.cbSize = (uint)Marshal.SizeOf(i); if (!GetLastInputInfo(ref i)) return 0; return unchecked((uint)Environment.TickCount - i.dwTime); }
'@
if (Get-Process LogonUI -ErrorAction SilentlyContinue) { exit 3 }
if ([McType.Native]::IdleMs() -lt $IdleSec * 1000) { exit 4 }

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms
$AE = [Windows.Automation.AutomationElement]

function Find-ClaudeWindow {
    foreach ($p in Get-Process Claude -ErrorAction SilentlyContinue | Where-Object MainWindowHandle -ne 0) {
        $c = New-Object Windows.Automation.PropertyCondition($AE::ProcessIdProperty, $p.Id)
        $w = $AE::RootElement.FindFirst('Children', $c)
        if ($w) { return $w }
    }
    $null
}
function Get-Prompt($w) {
    $c = New-Object Windows.Automation.AndCondition(
        (New-Object Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [Windows.Automation.ControlType]::Edit)),
        (New-Object Windows.Automation.PropertyCondition($AE::NameProperty, 'Prompt')))
    $w.FindFirst('Descendants', $c)
}
function Get-SessionDoc($w) {
    $c = New-Object Windows.Automation.PropertyCondition($AE::AutomationIdProperty, 'RootWebArea')
    foreach ($d in $w.FindAll('Descendants', $c)) { if ($d.Current.Name -like '* - Claude Code') { return $d.Current.Name } }
    ''
}

Start-Process "claude://claude.ai/epitaxy/$Local"
$want = $Title.Trim()
$w = $null; $prompt = $null; $doc = ''
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    $w = Find-ClaudeWindow
    if (-not $w) { continue }
    $doc = Get-SessionDoc $w
    if ($doc -and $doc.StartsWith($want.Substring(0, [Math]::Min(40, $want.Length)))) { $prompt = Get-Prompt $w; if ($prompt) { break } }
}
if (-not $w -or -not $prompt) { if ($doc) { Write-Output "open: $doc"; exit 7 } else { exit 6 } }

# Never mix with something Filip started typing at the PC.
$draft = ''
try { $draft = $prompt.GetCurrentPattern([Windows.Automation.TextPattern]::Pattern).DocumentRange.GetText(4000) } catch { }
if ($draft.Trim()) { exit 5 }

$old = $null
try { if ([Windows.Forms.Clipboard]::ContainsText()) { $old = [Windows.Forms.Clipboard]::GetText() } } catch { }
[Windows.Forms.Clipboard]::SetText($text)
$prompt.SetFocus()
Start-Sleep -Milliseconds 300
[Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 500
$typed = ''
try { $typed = $prompt.GetCurrentPattern([Windows.Automation.TextPattern]::Pattern).DocumentRange.GetText(8000) } catch { }
$probe = ($text.Trim() -split "`n")[0].Trim()
if ($typed -and -not $typed.Contains($probe.Substring(0, [Math]::Min(30, $probe.Length)))) {
    Write-Output 'paste check failed'
    exit 6
}
[Windows.Forms.SendKeys]::SendWait('{ENTER}')
Start-Sleep -Milliseconds 800
try { if ($null -ne $old) { [Windows.Forms.Clipboard]::SetText($old) } else { [Windows.Forms.Clipboard]::Clear() } } catch { }
exit 0
