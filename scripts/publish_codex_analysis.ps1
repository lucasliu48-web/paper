$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo
$env:HTTPS_PROXY = 'http://127.0.0.1:18081'
$env:HTTP_PROXY = $env:HTTPS_PROXY

function Run-Checked {
    $command = $args[0]
    $commandArgs = $args[1..($args.Count - 1)]
    & $command @commandArgs
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $command" }
}

if (git status --porcelain) { throw 'Repository has uncommitted changes; analysis update skipped.' }
Run-Checked git -c http.proxy=http://127.0.0.1:18081 -c http.sslBackend=openssl fetch origin main
Run-Checked git rebase origin/main
Run-Checked python scripts/update_codex_analysis.py --limit 20
Run-Checked git add codex_analyses.json
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Write-Output 'No new analyses to publish'; exit 0 }
Run-Checked git commit -m 'Update Codex RSS analyses'
Run-Checked git -c http.proxy=http://127.0.0.1:18081 -c http.sslBackend=openssl pull --rebase origin main
Run-Checked git -c http.proxy=http://127.0.0.1:18081 -c http.sslBackend=openssl push origin main
Run-Checked gh workflow run rss_action.yaml --ref main
Write-Output 'Published Codex analyses and started Pages deployment'
