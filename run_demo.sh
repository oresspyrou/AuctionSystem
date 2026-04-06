#!/bin/bash
rm -rf shared_directories
echo "Starting Auction Server..."
java -cp out AuctionServer &
sleep 2

for i in 1 2 3 4 5; do
    echo "Starting peer$i..."
    java -cp out Peer "peer$i" "pass$i" auto &
    sleep 1
done

echo "Demo running. Press Ctrl+C to stop all."
wait
