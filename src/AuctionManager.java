import java.util.*;

// runs in its own thread, picks items from the queue and runs auctions one at a time
public class AuctionManager extends Thread {

    private AuctionServer server;
    private boolean running = true;

    public AuctionManager(AuctionServer server) {
        this.server = server;
        this.setDaemon(true); // so it doesn't block shutdown
    }

    @Override
    public void run() {
        server.log("AuctionManager started, waiting for items...");

        while (running) {
            try {
                // wait for an item to appear in the queue
                AuctionItem item = null;
                synchronized (server.auctionQueue) {
                    while (server.auctionQueue.isEmpty()) {
                        server.auctionQueue.wait();
                    }
                    item = server.auctionQueue.remove(0);
                }

                // set up the auction
                synchronized (server.auctionLock) {
                    server.currentObjectId = item.objectId;
                    server.currentDescription = item.description;
                    server.sellerTokenId = item.sellerTokenId;
                    server.trexousaBid = item.startBid;
                    server.highestBidderTokenId = null;
                    server.auctionEndTime = System.currentTimeMillis() + item.duration * 1000L;
                }

                // count this auction for the seller
                server.incrementCounter(item.sellerTokenId, true);

                server.log("=== AUCTION START === " + item.objectId
                        + " | " + item.description
                        + " | starting bid: " + item.startBid
                        + " | duration: " + item.duration + "s");

                // wait until the auction timer runs out
                // we check every second
                while (true) {
                    long timeLeft;
                    synchronized (server.auctionLock) {
                        timeLeft = server.auctionEndTime - System.currentTimeMillis();
                        // if auction was cancelled (e.g. seller disconnected), stop waiting
                        if (server.currentObjectId == null) {
                            server.log("=== AUCTION CANCELLED === " + item.objectId);
                            break;
                        }
                    }
                    if (timeLeft <= 0) break;
                    Thread.sleep(1000);
                }

                // auction is over, figure out the result
                synchronized (server.auctionLock) {
                    // could have been cancelled already
                    if (server.currentObjectId == null) {
                        continue;
                    }

                    if (server.highestBidderTokenId != null) {
                        // someone won
                        String winnerId = server.highestBidderTokenId;
                        double finalBid = server.trexousaBid;
                        String sellerId = server.sellerTokenId;

                        server.log("=== AUCTION END === " + item.objectId
                                + " won by " + winnerId + " for " + finalBid);

                        // get seller info to send to winner
                        PeerInfo sellerInfo;
                        synchronized (server.activePeers) {
                            sellerInfo = server.activePeers.get(sellerId);
                        }

                        // tell the winner
                        if (sellerInfo != null) {
                            String wonMsg = "AUCTION_WON|" + item.objectId + "|" + finalBid
                                    + "|" + sellerInfo.ipAddress + "|" + sellerInfo.port
                                    + "|" + sellerId;
                            server.sendToPeer(winnerId, wonMsg);
                        }

                        // tell the seller
                        String soldMsg = "AUCTION_SOLD|" + item.objectId + "|" + finalBid
                                + "|" + winnerId;
                        server.sendToPeer(sellerId, soldMsg);

                        // update bidder counter and remove item from seller's list
                        server.incrementCounter(winnerId, false);
                        server.removeItemFromPeer(sellerId, item.objectId);

                    } else {
                        // no bids were placed
                        server.log("=== AUCTION END === " + item.objectId + " - no bids received");
                        server.sendToPeer(server.sellerTokenId,
                                "AUCTION_ENDED|" + item.objectId + "|No bids received");
                    }

                    // clear auction state
                    server.currentObjectId = null;
                    server.currentDescription = null;
                    server.sellerTokenId = null;
                    server.trexousaBid = 0;
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
