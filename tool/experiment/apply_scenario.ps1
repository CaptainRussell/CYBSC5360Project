<#
Applies one tampering scenario inside the Windows test VM and records an answer
key, so the correct answer is known before ADS runs (evaluation plan, Section
IV-B). Run this INSIDE the VM, elevated (Run as Administrator).

The answer key is written in the exact format ADS reads as ground truth
(ads/evaluate.py):  entry_number,sequence_number,path,category,host_time_utc,snapshot
Rows give the path only; ADS matches them to the parsed MFT by path, so the
entry and sequence columns are left blank.

  .\apply_scenario.ps1 -Scenario T1 -Snapshot test01 -Key C:\answer_key.csv -Confirm

WARNING: scenarios change this machine on purpose. T4 clears event logs, T5
deletes the change journal, T7 moves the clock. Only run inside a throwaway VM
whose state you have snapshotted. Nothing happens without -Confirm.

Scenarios (match Table III of the evaluation plan):
  T1  Change a file's visible (SI) dates
  T2  Change SI and FN together        (needs an outside tool; see -SiFnCommand)
  T3  Make a brand-new file look old
  T4  Clear the event logs
  T5  Delete the change journal
  T6  Delete shortcuts and Prefetch
  T7  Change the system clock around a file write
  T8  T1 then T4+T5+T6 (a careful adversary)

Why files are "opened" first: the shortcut rules (R2, R3, R4, R9) can only
check a file that has a shortcut. Windows writes one to the Recent folder when a
user opens a document. Each file-level scenario therefore makes its file, opens
it the way Explorer does (SHAddToRecentDocs, the call that writes that
shortcut), waits -WaitSeconds so the shortcut's times are distinct, and only then
tampers. Without this every tampered file would have no shortcut and those four
rules could never be evaluated on it.

T2 needs a tool that sets the protected FN dates as well as SI (PowerShell can
only set SI). Tools differ in syntax, so give the command yourself, with {file}
where the file path goes, after checking that tool's own documentation. For
example (check before use, do not assume):
  -SiFnCommand 'C:\tools\SetMace.exe "{file}" -z "2019:03:01:12:00:00:000:0000000"'
#>
param(
    [Parameter(Mandatory)] [ValidateSet("T1","T2","T3","T4","T5","T6","T7","T8")] [string]$Scenario,
    [Parameter(Mandatory)] [string]$Snapshot,
    [string]$Key = "answer_key.csv",
    [string]$WorkDir = "$env:USERPROFILE\Documents\ads_lab",
    [int]$WaitSeconds = 120,        # gap between "opening" a file and tampering with it
    [string]$SiFnCommand = "",      # T2 only: command line for an SI+FN tool, with {file}
    [switch]$Confirm
)
$ErrorActionPreference = "Stop"

# The reference time is recorded BEFORE any clock change, in UTC. For T7 the
# examiner should reconcile against the host clock, per the evaluation plan.
function NowUtc { (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss") }

if (-not (Test-Path $Key)) {
    "entry_number,sequence_number,path,category,host_time_utc,snapshot" | Out-File -Encoding utf8 $Key
}
function Add-Key([string]$Path, [string]$Category) {
    $p = $Path -replace '"','""'
    ",,`"$p`",$Category,$(NowUtc),$Snapshot" | Out-File -Encoding utf8 -Append $Key
    Write-Host "  answer key += [$Category] $Path"
}

if (-not $Confirm) {
    Write-Host "Dry run. This would apply scenario $Scenario. Re-run with -Confirm to make the changes." -ForegroundColor Yellow
    return
}
if ($Scenario -eq "T2" -and -not $SiFnCommand) {
    throw "T2 needs -SiFnCommand (a tool that sets SI and FN dates). See the notes at the top of this script."
}
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Write-Host "Applying $Scenario (snapshot '$Snapshot') ..." -ForegroundColor Cyan

# SHAddToRecentDocs is what Explorer calls when a user opens a document: it writes
# the shortcut in %APPDATA%\Microsoft\Windows\Recent, with a copy of the target's dates.
Add-Type -Namespace AdsLab -Name Shell -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("shell32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
public static extern void SHAddToRecentDocs(uint flags, string path);
'@
function Open-AsUser([string]$Path) {
    [AdsLab.Shell]::SHAddToRecentDocs(3, $Path)      # 3 = SHARD_PATHW
    Get-Content -Path $Path | Out-Null               # a real read, as an application would do
    Write-Host "  opened $Path (shortcut written); waiting $WaitSeconds s before tampering"
    Start-Sleep -Seconds $WaitSeconds
}
function New-Sample([string]$Name, [string]$Text = "lab sample file") {
    $p = Join-Path $WorkDir $Name
    Set-Content -Path $p -Value $Text -Encoding UTF8
    return $p
}
function Set-SiDates([string]$Path, [datetime]$When) {
    $i = Get-Item $Path
    $i.CreationTime = $When; $i.LastWriteTime = $When; $i.LastAccessTime = $When
}
function Clear-Logs { foreach ($log in "System","Security","Application") { wevtutil cl $log } }
function Remove-Journal {
    $vol = (Get-Item $WorkDir).PSDrive.Name + ":"
    fsutil usn deletejournal /d $vol
}
function Remove-Traces {
    Get-ChildItem "$env:APPDATA\Microsoft\Windows\Recent\*.lnk" -ErrorAction SilentlyContinue | Remove-Item -Force
    Get-ChildItem "C:\Windows\Prefetch\*.pf" -ErrorAction SilentlyContinue | Remove-Item -Force
}

switch ($Scenario) {
    "T1" {
        $f = New-Sample "t1_report.txt"
        Open-AsUser $f
        Set-SiDates $f ([datetime]"2019-03-01 12:00:00")     # set the visible dates back
        Add-Key $f "T1"
    }
    "T2" {
        $f = New-Sample "t2_notes.txt"
        Open-AsUser $f
        $cmd = $SiFnCommand.Replace("{file}", $f)
        Write-Host "  running: $cmd"
        cmd.exe /c $cmd
        if ($LASTEXITCODE -ne 0) { throw "the SI+FN tool failed (exit $LASTEXITCODE); nothing was recorded" }
        Add-Key $f "T2"
    }
    "T3" {
        $f = New-Sample "t3_invoice.txt" "freshly made, backdated to look old"
        Open-AsUser $f
        Set-SiDates $f ([datetime]"2015-01-01 09:00:00")
        Add-Key $f "T3"
    }
    "T4" { Clear-Logs;     Add-Key "(system)" "T4" }
    "T5" { Remove-Journal; Add-Key "(system)" "T5" }
    "T6" { Remove-Traces;  Add-Key "(system)" "T6" }
    "T7" {
        $real = Get-Date
        Set-Date ($real.AddYears(-3)) | Out-Null       # move the clock back
        try {
            $f = New-Sample "t7_photo_meta.txt" "written while the clock was wrong"
            [AdsLab.Shell]::SHAddToRecentDocs(3, $f)
            Add-Key $f "T7"
        } finally {
            Set-Date $real | Out-Null                  # always put the clock back
        }
    }
    "T8" {
        $f = New-Sample "t8_ledger.txt"
        Open-AsUser $f
        Set-SiDates $f ([datetime]"2018-06-01 08:00:00")
        Add-Key $f "T8"
        Clear-Logs; Remove-Journal; Remove-Traces
    }
}
Write-Host "Done. Answer key: $Key" -ForegroundColor Green
Write-Host "Next: take the VM snapshot, image it, run run_parsers.ps1, then 'python -m ads analyze' and 'evaluate --truth $Key'."
