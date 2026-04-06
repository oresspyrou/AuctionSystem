@echo off
if exist shared_directories rmdir /s /q shared_directories
echo Starting Auction Server...
start /b java -cp out AuctionServer
timeout /t 2 /nobreak >nul

for %%i in (1 2 3 4 5) do (
    echo Starting peer%%i...
    start /b java -cp out Peer "peer%%i" "pass%%i" auto
    timeout /t 1 /nobreak >nul
)

echo Demo running. Press Ctrl+C to stop all.
pause >nul
