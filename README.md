# fm_air_client

Client side Raspberry pi 2

## Run
Set MySQL connection via env vars (recommended):
- `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`

Example:
- PowerShell: `$env:MYSQL_HOST="..."; $env:MYSQL_USER="..."; $env:MYSQL_PASSWORD="..."; python -m clinet`
- Linux/Raspberry Pi: `MYSQL_HOST=... MYSQL_USER=... MYSQL_PASSWORD=... python -m clinet`