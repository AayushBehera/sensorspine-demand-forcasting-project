# Restart the API server and wait until it actually answers.
param([int]$Port = 8000)
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) { $existing | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }; Start-Sleep 1 }
Start-Process -FilePath "python" `
  -ArgumentList "-m","uvicorn","app.main:app","--port","$Port" `
  -PassThru -WindowStyle Hidden `
  -RedirectStandardError "$env:TEMP\uv_err.txt" `
  -RedirectStandardOutput "$env:TEMP\uv_out.txt" | Out-Null
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep 1
  try {
    $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
    if ($r.StatusCode -eq 200) { "server ready after ${i}s"; exit 0 }
  } catch {}
}
"server FAILED to start:"; Get-Content "$env:TEMP\uv_err.txt" -Tail 20; exit 1
