import java.util.*;

// polls the server every POLL_INTERVAL seconds to check if there's an active auction
// if there is, decides whether to bid (60% chance) and places a bid
public class AuctionPoller extends Thread {

    private Peer peer;
    private boolean running = true;

    public AuctionPoller(Peer peer) {
        this.peer = peer;
        this.setDaemon(true);
    }

    public void stopRunning() {
        running = false;
        this.interrupt();
    }

    @Override
    public void run() {
        peer.log("AuctionPoller started, polling every " + Config.POLL_INTERVAL + "s");

        while (running) {
            try {
                Thread.sleep(Config.POLL_INTERVAL * 1000);

                String token = peer.getTokenId();
                if (token == null) {
                    // not logged in anymore, stop
                    break;
                }

                // 1. ask server what's being auctioned right now
                String currentResponse = peer.sendToServer("GET_CURRENT_AUCTION|" + token);
                if (currentResponse == null) continue;

                if (currentResponse.startsWith("NO_AUCTION")) {
                    peer.log("No active auction right now");
                    continue;
                }

                // CURRENT_AUCTION|object_id|description
                String[] currentParts = currentResponse.split("\\|");
                if (currentParts.length < 3) continue;

                String objectId = currentParts[1];
                String description = currentParts[2];

                peer.log("Current auction: " + objectId + " - " + description);

                // don't bid on our own items
                boolean isMyItem = false;
                synchronized (peer.myItems) {
                    isMyItem = peer.myItems.contains(objectId);
                }
                if (isMyItem) {
                    peer.log("Skipping - this is our own item");
                    continue;
                }

                // 2. coin flip: 60% chance we're interested
                if (Math.random() > Config.INTEREST_PROBABILITY) {
                    peer.log("Not interested in " + objectId + " (coin flip)");
                    continue;
                }

                // 3. get auction details
                String detailsResponse = peer.sendToServer("GET_AUCTION_DETAILS|" + token);
                if (detailsResponse == null || !detailsResponse.startsWith("AUCTION_DETAILS")) {
                    continue;
                }

                // AUCTION_DETAILS|seller_token|highest_bid|time_remaining
                String[] detailParts = detailsResponse.split("\\|");
                if (detailParts.length < 4) continue;

                String sellerToken = detailParts[1];
                double highestBid = Double.parseDouble(detailParts[2]);
                long timeLeft = Long.parseLong(detailParts[3]);

                peer.log("Details: highest bid=" + highestBid + ", time left=" + timeLeft + "s");

                if (timeLeft <= 0) {
                    peer.log("Auction already ended, skipping");
                    continue;
                }

                // 4. calculate our bid: NewBid = HighestBid * (1 + RAND/10)
                double newBid = highestBid * (1 + Math.random() / 10);
                // round to 2 decimal places
                newBid = Math.round(newBid * 100.0) / 100.0;

                // 5. place the bid
                String bidMsg = "PLACE_BID|" + token + "|" + objectId + "|" + newBid;
                String bidResponse = peer.sendToServer(bidMsg);
                peer.log("Placed bid " + newBid + " on " + objectId + ": " + bidResponse);

            } catch (InterruptedException e) {
                if (!running) break;
            } catch (Exception e) {
                peer.log("AuctionPoller error: " + e.getMessage());
            }
        }

        peer.log("AuctionPoller stopped");
    }
}
