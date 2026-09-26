# Move databases to NVMe (16.09.2026). Run from an ELEVATED PowerShell:
#     & "E:\MTF BOT\CURSOR\crypto_volume_bot\scripts\move_dbs_to_nvme.ps1"
# Stops pm2 services -> moves ohlcv_cache.db (19 GB) and subscriptions.db to C:\oko_data ->
# creates symbolic links in their old places (code paths stay the same) -> starts services back.
# Admin rights are needed only for the symbolic links. Log: C:\oko_data\move_log.txt
# ASCII-only on purpose: the earlier .cmd version died on UTF-8 box-drawing characters.

$ErrorActionPreference = 'Stop'
$repo = 'E:\MTF BOT\CURSOR\crypto_volume_bot'
$dest = 'C:\oko_data'
$dbs  = @('ohlcv_cache.db', 'subscriptions.db')

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "NOT ADMIN. Open 'Terminal (Administrator)' (Win+X) and run this script again." -ForegroundColor Red
    return
}

New-Item -ItemType Directory -Force -Path $dest | Out-Null
$log = Join-Path $dest 'move_log.txt'
function Note($m) { $line = "[{0:HH:mm:ss}] {1}" -f (Get-Date), $m; Write-Host $line; Add-Content -Path $log -Value $line -Encoding UTF8 }

Note "=== start ==="
try {
    Note "1/5 stopping pm2 services"
    & pm2 stop all 2>&1 | Out-Null
    Start-Sleep -Seconds 5
    Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3

    Note "2/5 moving databases (19 GB, few minutes)"
    foreach ($db in $dbs) {
        $src = Join-Path $repo $db
        if (Test-Path $src) {
            $size = [Math]::Round((Get-Item $src).Length / 1GB, 1)
            Note ("   {0} ({1} GB)" -f $db, $size)
            Move-Item -LiteralPath $src -Destination (Join-Path $dest $db) -Force
        }
        foreach ($sfx in @('-wal', '-shm')) {
            $s2 = Join-Path $repo ($db + $sfx)
            if (Test-Path $s2) { Move-Item -LiteralPath $s2 -Destination $dest -Force }
        }
    }

    Note "3/5 creating symbolic links"
    foreach ($db in $dbs) {
        $target = Join-Path $dest $db
        $link = Join-Path $repo $db
        if (Test-Path $target) {
            try {
                New-Item -ItemType SymbolicLink -Path $link -Target $target -Force | Out-Null
                Note ("   link ok: {0}" -f $db)
            } catch {
                Note ("   LINK FAILED for {0}: {1} -> moving file back" -f $db, $_.Exception.Message)
                Move-Item -LiteralPath $target -Destination $link -Force
            }
        }
    }

    Note "4/5 starting services"
    & pm2 start all 2>&1 | Out-Null
    Start-Sleep -Seconds 10

    Note "5/5 check"
    foreach ($db in $dbs) {
        $i = Get-Item (Join-Path $repo $db) -ErrorAction SilentlyContinue
        if ($i) { Note ("   {0}: type={1} target={2}" -f $db, $i.LinkType, ($i.Target -join ',')) } else { Note ("   {0}: MISSING" -f $db) }
    }
    Get-ChildItem $dest | ForEach-Object { Note ("   {0} in {1}: {2:N1} GB" -f $_.Name, $dest, ($_.Length / 1GB)) }
    & pm2 list
} catch {
    Note ("ERROR: " + $_.Exception.Message)
    Note "starting services back"
    & pm2 start all 2>&1 | Out-Null
}
Note "=== done, log: $log ==="
