<#
Runs Eric Zimmerman's parsers over artifacts exported from a test image and
hashes every export and every CSV (extraction stage, Section III-G step 1).

Assumes the artifacts were exported (for example with FTK Imager or KAPE) into
$Export with the volume's folder layout, i.e.
  $Export\$MFT
  $Export\$Extend\$J
  $Export\Windows\Prefetch\*.pf
  $Export\Users\<user>\AppData\Roaming\Microsoft\Windows\Recent\*.lnk
  $Export\Windows\System32\winevt\Logs\{System,Security,Application}.evtx

--mp makes PECmd and LECmd write 7-digit sub-second timestamps. Without it
they round to whole seconds and the LNK rules (R2-R4, R9) lose precision.

Usage:
  .\run_parsers.ps1 -Tools C:\Tools\EZ -Export E:\case01\export -Out E:\case01\csv
Then on any machine with Python 3:
  python -m ads ingest --db case01.sqlite --mft mft.csv --usn usn.csv --lnk lnk.csv `
      --prefetch prefetch.csv --evtx evtx_system.csv evtx_security.csv evtx_application.csv `
      --config case01.json     # set "mount_prefix" if LNK paths carry an export prefix
#>
param(
    [Parameter(Mandatory)] [string]$Tools,
    [Parameter(Mandatory)] [string]$Export,
    [Parameter(Mandatory)] [string]$Out
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

& "$Tools\MFTECmd.exe" -f "$Export\`$MFT" --csv $Out --csvf mft.csv
& "$Tools\MFTECmd.exe" -f "$Export\`$Extend\`$J" -m "$Export\`$MFT" --csv $Out --csvf usn.csv
& "$Tools\PECmd.exe" -d "$Export\Windows\Prefetch" --csv $Out --csvf prefetch.csv --mp
& "$Tools\LECmd.exe" -d "$Export\Users" --csv $Out --csvf lnk.csv --mp
foreach ($log in "System", "Security", "Application") {
    & "$Tools\EvtxECmd\EvtxECmd.exe" -f "$Export\Windows\System32\winevt\Logs\$log.evtx" `
        --csv $Out --csvf ("evtx_{0}.csv" -f $log.ToLower())
}

# Chain of custody: hash every exported artifact and every CSV.
$hashes = Get-ChildItem -Recurse -File $Export, $Out | Get-FileHash -Algorithm SHA256
$hashes | Select-Object Hash, Path | Export-Csv -NoTypeInformation (Join-Path $Out "hashes.csv")
