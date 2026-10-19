# Keep the Sumika role-model loopback tunnel alive across SSH drops.
# Endpoint: 127.0.0.1:18083 -> laptop llama.cpp 8083.
$ErrorActionPreference = 'SilentlyContinue'
$ssh = 'C:\Windows\System32\OpenSSH\ssh.exe'
$arguments = @(
  '-N', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
  '-o', 'ServerAliveInterval=30', '-L', '18083:127.0.0.1:8083',
  'lostrain@192.168.31.227'
)
while ($true) {
  & $ssh @arguments
  Start-Sleep -Seconds 5
}
