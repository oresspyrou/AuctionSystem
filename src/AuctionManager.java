import java.util.*;

public class AuctionManager extends Thread {

    private AuctionServer server;
    private boolean running = true;

    public AuctionManager(AuctionServer server) {
        this.server = server;
        this.setDaemon(true);
    }

    @Override
    public void run() {
        server.log("AuctionManager started, waiting for items...");

        while (running) {
            try {
                AuctionItem item = null;
                synchronized (server.auctionQueue) {
                    while (server.auctionQueue.isEmpty()) {
                        server.auctionQueue.wait();
                    }
                    item = server.auctionQueue.remove(0);
                }

                synchronized (server.auctionLock) {
                    server.currentObjectId = item.objectId;
                    server.currentDescription = item.description;
                    server.sellerTokenId = item.sellerTokenId;
                    server.currentBid = item.startBid;
                    server.highestBidderTokenId = null;
                    server.auctionEndTime = System.currentTimeMillis() + item.duration * 1000L;
                }

                server.incrementCounter(item.sellerTokenId, true);

                server.log("=== AUCTION START === " + item.objectId);
                
                // ΒΕΛΤΙΩΣΗ: Ενημέρωση όλων των Peers ότι ξεκίνησε δημοπρασία
                server.broadcastToAll("AUCTION_START|" + item.objectId + "|" + item.description + "|" + item.startBid);

                while (true) {
                    long timeLeft;
                    synchronized (server.auctionLock) {
                        timeLeft = server.auctionEndTime - System.currentTimeMillis();
                        if (server.currentObjectId == null) break; 
                    }
                    if (timeLeft <= 0) break;
                    Thread.sleep(1000);
                }

                synchronized (server.auctionLock) {
                    if (server.currentObjectId == null) continue;

                    if (server.highestBidderTokenId != null) {
                        String winnerId = server.highestBidderTokenId;
                        double finalBid = server.currentBid;
                        String sellerId = server.sellerTokenId;

                        server.log("=== AUCTION END === " + item.objectId + " won by " + winnerId);

                        // ΒΕΛΤΙΩΣΗ: Δεν χρειάζεται synchronized εδώ λόγω ConcurrentHashMap
                        PeerInfo sellerInfo = server.activePeers.get(sellerId);

                        if (sellerInfo != null) {
                            String wonMsg = "AUCTION_WON|" + item.objectId + "|" + finalBid
                                    + "|" + sellerInfo.ipAddress + "|" + sellerInfo.port
                                    + "|" + sellerId;
                            server.sendToPeer(winnerId, wonMsg);
                        }

                        String soldMsg = "AUCTION_SOLD|" + item.objectId + "|" + finalBid + "|" + winnerId;
                        server.sendToPeer(sellerId, soldMsg);

                        server.incrementCounter(winnerId, false);
                        server.removeItemFromPeer(sellerId, item.objectId);
                        
                        // Ενημέρωση όλων για το κλείσιμο
                        server.broadcastToAll("AUCTION_CLOSED|" + item.objectId + "|Winner: " + winnerId);

                    } else {
                        server.log("=== AUCTION END === " + item.objectId + " - no bids");
                        
                        // Ενημέρωση όλων ότι έληξε χωρίς νικητή
                        server.broadcastToAll("AUCTION_CLOSED|" + item.objectId + "|No bids received");
                    }

                    // Reset state
                    server.currentObjectId = null;
                    server.currentDescription = null;
                    server.sellerTokenId = null;
                    server.currentBid = 0;
                    server.highestBidderTokenId = null;
                    server.auctionEndTime = 0;
                }

            } catch (InterruptedException e) {
                server.log("AuctionManager interrupted");
                running = false;
            }
        }
    }
}
