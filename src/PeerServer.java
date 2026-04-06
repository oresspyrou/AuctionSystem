import java.io.*;
import java.net.*;

// listens on a random port for incoming connections:
// - CHECK_ACTIVE pings from the server
// - AUCTION_WON / AUCTION_SOLD / BID_UPDATE / AUCTION_CANCELLED notifications from server
// - TRANSACTION_REQUEST from buyer peers (when we are the seller)
public class PeerServer extends Thread {

    private Peer peer;
    private ServerSocket serverSocket;
    private boolean running = true;

    public PeerServer(Peer peer) {
        this.peer = peer;
        this.setDaemon(true);
        try {
            // port 0 = OS picks a random available port
            serverSocket = new ServerSocket(0);
        } catch (IOException e) {
            peer.log("Could not start PeerServer: " + e.getMessage());
        }
    }

    public int getPort() {
        return serverSocket.getLocalPort();
    }

    public void stopRunning() {
        running = false;
        try {
            serverSocket.close();
        } catch (IOException e) {
            // ignore
        }
    }

    @Override
    public void run() {
        while (running) {
            try {
                Socket incoming = serverSocket.accept();
                // handle each incoming connection in a new thread
                final Socket conn = incoming;
                new Thread() {
                    public void run() {
                        handleConnection(conn);
                    }
                }.start();
            } catch (IOException e) {
                if (running) {
                    peer.log("PeerServer accept error: " + e.getMessage());
                }
            }
        }
    }

    private void handleConnection(Socket socket) {
        try {
            DataInputStream in = new DataInputStream(socket.getInputStream());
            DataOutputStream out = new DataOutputStream(socket.getOutputStream());

            String message = MessageHelper.receiveMessage(in);
            String[] parts = message.split("\\|");
            String type = parts[0];

            switch (type) {
                case "CHECK_ACTIVE":
                    MessageHelper.sendMessage(out, "CHECK_ACTIVE_ACK|pong");
                    break;

                case "AUCTION_WON":
                    handleAuctionWon(parts);
                    break;

                case "AUCTION_SOLD":
                    handleAuctionSold(parts);
                    break;

                case "BID_UPDATE":
                    handleBidUpdate(parts);
                    break;

                case "AUCTION_CANCELLED":
                    handleAuctionCancelled(parts);
                    break;

                case "AUCTION_ENDED":
                    // no bids were placed on our item
                    peer.log("Auction ended for " + parts[1] + ": " + parts[2]);
                    break;

                case "TRANSACTION_REQUEST":
                    handleTransactionRequest(parts, out);
                    break;

                default:
                    peer.log("PeerServer received unknown message: " + type);
                    break;
            }

            socket.close();

        } catch (IOException e) {
            peer.log("PeerServer connection error: " + e.getMessage());
        }
    }

    // AUCTION_WON|object_id|bid|seller_ip|seller_port|seller_token
    // we won! connect to the seller and get the item
    private void handleAuctionWon(String[] parts) {
        if (parts.length < 6) return;

        String objectId = parts[1];
        double finalBid = Double.parseDouble(parts[2]);
        String sellerIp = parts[3];
        int sellerPort = Integer.parseInt(parts[4]);
        String sellerToken = parts[5];

        peer.log("WON auction for " + objectId + " at price " + finalBid);

        // connect to the seller peer-to-peer to get the metadata file
        try {
            Socket sellerSocket = new Socket(sellerIp, sellerPort);
            DataOutputStream out = new DataOutputStream(sellerSocket.getOutputStream());
            DataInputStream in = new DataInputStream(sellerSocket.getInputStream());

            // send transaction request
            String request = "TRANSACTION_REQUEST|" + objectId + "|" + finalBid + "|" + peer.getTokenId();
            MessageHelper.sendMessage(out, request);

            // receive the metadata
            String response = MessageHelper.receiveMessage(in);
            sellerSocket.close();

            if (response != null && response.startsWith("TRANSACTION_RESPONSE")) {
                String[] respParts = response.split("\\|", 3);
                if (respParts.length >= 3) {
                    // save the metadata file to our shared_directory
                    String metadata = respParts[2];
                    String filePath = peer.sharedDir + "/" + objectId + ".txt";

                    FileWriter fw = new FileWriter(filePath);
                    fw.write(metadata);
                    fw.close();

                    peer.log("Saved " + objectId + " metadata to " + filePath);

                    // tell the server we now own this item
                    AuctionItem item = AuctionItem.parseFromFile(filePath);
                    if (item != null) {
                        synchronized (peer.myItems) {
                            peer.myItems.add(objectId);
                        }
                        peer.sendNewItem(item);
                    }
                }
            }

        } catch (IOException e) {
            peer.log("Transaction failed for " + objectId + ": " + e.getMessage());
        }
    }

    // AUCTION_SOLD|object_id|bid|buyer_token
    // our item was sold, buyer will connect to us for the file
    private void handleAuctionSold(String[] parts) {
        if (parts.length < 4) return;
        String objectId = parts[1];
        double finalBid = Double.parseDouble(parts[2]);
        String buyerToken = parts[3];
        peer.log("SOLD " + objectId + " for " + finalBid + " to " + buyerToken);
        // the actual file transfer happens when buyer sends TRANSACTION_REQUEST
    }

    // TRANSACTION_REQUEST|object_id|bid|buyer_token
    // buyer is asking us for the metadata file
    private void handleTransactionRequest(String[] parts, DataOutputStream out) {
        if (parts.length < 4) return;

        String objectId = parts[1];
        double bid = Double.parseDouble(parts[2]);
        String buyerToken = parts[3];

        peer.log("Transaction request from " + buyerToken + " for " + objectId + " at " + bid);

        String filePath = peer.sharedDir + "/" + objectId + ".txt";
        File file = new File(filePath);

        try {
            if (file.exists()) {
                // read the metadata and send it
                AuctionItem item = AuctionItem.parseFromFile(filePath);
                if (item != null) {
                    String fileContent = "object_id: " + item.objectId
                            + "; description: " + item.description
                            + "; start_bid: " + item.startBid
                            + "; auction_duration: " + item.duration;

                    MessageHelper.sendMessage(out, "TRANSACTION_RESPONSE|" + objectId + "|" + fileContent);

                    // delete the file from our shared_directory
                    file.delete();
                    synchronized (peer.myItems) {
                        peer.myItems.remove(objectId);
                    }
                    peer.log("Sent metadata and deleted " + objectId + " from shared_directory");
                }
            } else {
                MessageHelper.sendMessage(out, "TRANSACTION_FAIL|" + objectId + "|File not found");
                peer.log("Transaction failed: " + objectId + " not found in shared_directory");
            }
        } catch (IOException e) {
            peer.log("Error during transaction for " + objectId + ": " + e.getMessage());
        }
    }

    // BID_UPDATE|object_id|new_bid|bidder_token
    private void handleBidUpdate(String[] parts) {
        if (parts.length < 4) return;
        peer.log("Bid update: " + parts[1] + " new highest bid " + parts[2] + " by " + parts[3]);
    }

    // AUCTION_CANCELLED|object_id|reason
    private void handleAuctionCancelled(String[] parts) {
        if (parts.length < 3) return;
        peer.log("Auction cancelled: " + parts[1] + " - " + parts[2]);
    }
}
