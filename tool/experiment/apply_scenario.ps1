<#
Applies one tampering scenario inside the Windows test VM and records an answer
key, so the correct answer is known before ADS runs (evaluation plan, Section
IV-B). Run this INSIDE the VM, elevated (Run as Administrator).

The answer key is written in the exact format ADS reads as ground truth
(ads/evaluate.py):  entry_number,sequence_number,path,category,host_time_utc,snapshot
A row may give only the path; entry/sequence are filled in later by the examiner
from the parsed MFT if wanted, so they are left blank here.

  .\apply_scenario.ps1 -Scenario T1 -Snapshot test01 -Key C:\answer_key.csv -Confirm

WARNING: scenarios change this machine on purpose. T4 clears event logs, T5
deletes the change journal, T7 moves the clock. Only run inside a throwaway VM
whose state you have snapshotted. Nothing happens without -Confirm.

Scenarios (match Table III of the evaluation plan):
  T1  Change a file's visible (SI) dates
  T2  Change SI and FN together        (needs an external tool; see note)
  T3  Make a brand-new file look old
  T4  Clear the event logs
  T5  Delete the change journal
  T6  Delete shortcuts and Prefetch
  T7  Change the system clock around a file write
  T8  T1 then T4+T5+T6 (a careful adversary)
#>
param(
    [Parameter(Mandatory)] [ValidateSet("T1","T2","T3","T4","T5","T6","T7","T8")] [string]$Scenario,
    [Parameter(Mandatory)] [string]$Snapshot,
    [string]$Key = "answer_key.csv",
    [string]$WorkDir = "$env:USERPROFILE\Documents\ads_lab",
    [string]$SetMACE = "",          # optional path to a SI+FN timestamp tool for T2/T8
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
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Write-Host "Applying $Scenario (snapshot '$Snapshot') ..." -ForegroundColor Cyan

function New-Sample([string]$Name, [string]$Text = "lab sample file") {
    $p = Join-Path $WorkDir $Name
    Set-Content -Path $p -Value $Text -Encoding UTF8
    return $p
}
function Set-SiDates([string]$Path, [datetime]$When) {
    $i = Get-Item $Path
    $i.CreationTime = $When; $i.LastWriteTime = $When; $i.LastAccessTime = $When
}

switch ($Scenario) {
    "T1" {
        $f = New-Sample "t1_report.docx"
        Set-SiDates $f ([datetime]"2019-03-01 12:00:00")     # set the visible dates back
        Add-Key $f "T1"
    }
    "T2" {
        $f = New-Sample "t2_notes.txt"
        if ($SetMACE -and (Test-Path $SetMACE)) {
            & $SetMACE -z "2019-03-01 12:00:00" "$f"           # tool sets SI and FN together
        } else {
            Set-SiDates $f ([datetime]"2019-03-01 12:00:00")
            Write-Host "  note: no SI+FN tool given, only SI set. R6 may not fire. See -SetMACE." -ForegroundColor Yellow
        }
        Add-Key $f "T2"
    }
    "T3" {
        $f = New-Sample "t3_invoice.pdf" "freshly made, backdated to look old"
        Set-SiDates $f ([datetime]"2015-01-01 09:00:00")
        Add-Key $f "T3"
    }
    "T4" {
        foreach ($log in "System","Security","Application") { wevtutil cl $log }
        Add-Key "(system)" "T4"
    }
    "T5" {
        $vol = (Get-Item $WorkDir).PSDrive.Name + ":"
        fsutil usn deletejournal /d $vol
        Add-Key "(system)" "T5"
    }
    "T6" {
        Get-ChildItem "$env:APPDATA\Microsoft\Windows\Recent\*.lnk" -ErrorAction SilentlyContinue | Remove-Item -Force
        Get-ChildItem "C:\Windows\Prefetch\*.pf" -ErrorAction SilentlyContinue | Remove-Item -Force
        Add-Key "(system)" "T6"
    }
    "T7" {
        $real = Get-Date
        Set-Date ($real.AddYears(-3)) | Out-Null       # move the clock back
        $f = New-Sample "t7_photo_meta.txt" "written while the clock was wrong"
        Add-Key $f "T7"
        Set-Date $real | Out-Null                      # put the clock back
    }
    "T8" {
        $f = New-Sample "t8_ledger.xlsx"
        Set-SiDates $f ([datetime]"2018-06-01 08:00:00")
        Add-Key $f "T8"
        foreach ($log in "System","Security","Application") { wevtutil cl $log }
        $vol = (Get-Item $WorkDir).PSDrive.Name + ":"
        fsutil usn deletejournal /d $vol
        Get-ChildItem "$env:APPDATA\Microsoft\Windows\Recent\*.lnk" -ErrorAction SilentlyContinue | Remove-Item -Force
        Get-ChildItem "C:\Windows\Prefetch\*.pf" -ErrorAction SilentlyContinue | Remove-Item -Force
    }
}
Write-Host "Done. Answer key: $Key" -ForegroundColor Green
Write-Host "Next: take the VM snapshot, image it, run run_parsers.ps1, then 'python -m ads analyze' and 'evaluate --truth $Key'."
