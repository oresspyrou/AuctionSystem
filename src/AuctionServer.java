import java.io.*;
import java.net.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class AuctionServer {

    // registered users: username -> [password, numSeller, numBidder]
    private Map<String, String[]> registeredUsers = new ConcurrentHashMap<>();

    // currently connected peers: tokenId -> PeerInfo
    Map<String, PeerInfo> activePeers = new ConcurrentHashMap<>();

    // items waiting to be auctioned, FCFS order
    ArrayList<AuctionItem> auctionQueue = new ArrayList<>();

    // all items submitted by each peer: tokenId -> list of items
    // this is separate from the queue - it tracks who has what
    private Map<String, List<AuctionItem>> peerItems = new ConcurrentHashMap<>();

    // current auction state - all access through synchronized(auctionLock)
    String currentObjectId = null;
    String currentDescription = null;
    String sellerTokenId = null;
    double currentBid = 0;
    String highestBidderTokenId = null;
    long auctionEndTime = 0;
    Object auctionLock = new Object();

    public static void main(String[] args) {
        AuctionServer server = new AuctionServer();
        server.start();
    }

    public void start() {
        try {
            ServerSocket serverSocket = new ServerSocket(Config.SERVER_PORT);
            log("Auction Server started on port " + Config.SERVER_PORT);

            // start the auction manager thread that runs auctions one by one
            AuctionManager auctionManager = new AuctionManager(this);
            auctionManager.start();

            // accept incoming connections
            while (true) {
                Socket clientSocket = serverSocket.accept();
                log("New connection from " + clientSocket.getInetAddress());
                ClientHandler handler = new ClientHandler(clientSocket, this);
                handler.start();
            }

        } catch (IOException e) {
            log("Server error: " + e.getMessage());
        }
    }

    // --- register / login / logout ---

    public String register(String username, String password) {
        String[] existing = registeredUsers.putIfAbsent(username, new String[]{password, "0", "0"});
        if (existing != null) {
            return "REGISTER_FAIL|Username already exists";
        }
        log("Registered new user: " + username);
        return "REGISTER_OK|Account created";
    }

    public String login(String username, String password, String ipAddress) {
        synchronized (registeredUsers) {
            if (!registeredUsers.containsKey(username)) {
                return "LOGIN_FAIL|User not found";
            }
            String[] userData = registeredUsers.get(username);
            if (!userData[0].equals(password)) {
                return "LOGIN_FAIL|Wrong password";
            }
        }

        // generate a random token
        String tokenId = "tok_" + (new Random().nextInt(90000) + 10000);

        // make sure it's unique
        synchronized (activePeers) {
            while (activePeers.containsKey(tokenId)) {
                tokenId = "tok_" + (new Random().nextInt(90000) + 10000);
            }
            // create PeerInfo with port=0 for now, will be updated on REQUEST_AUCTION
            PeerInfo info = new PeerInfo(tokenId, ipAddress, 0, username);
            activePeers.put(tokenId, info);
        }

        log("User logged in: " + username + " with token " + tokenId);
        return "LOGIN_OK|" + tokenId;
    }

    public String logout(String tokenId) {
        synchronized (activePeers) {
            PeerInfo peer = activePeers.remove(tokenId);
            if (peer != null) {
                log("User logged out: " + peer.username + " (token " + tokenId + ")");
            }
        }
        // clean up their item list
        synchronized (peerItems) {
            peerItems.remove(tokenId);
        }
        return "LOGOUT_OK|Bye";
    }

    // --- auction request ---

    public void addItemToQueue(AuctionItem item) {
        synchronized (auctionQueue) {
            auctionQueue.add(item);
            log("Item added to queue: " + item.objectId + " by seller " + item.sellerTokenId);
            auctionQueue.notifyAll();
        } 

        // Ατομική προσθήκη στη λίστα του peer μέσω CHM
        peerItems.computeIfAbsent(item.sellerTokenId, k -> Collections.synchronizedList(new ArrayList<>()))
                 .add(item);
    } 

    public void removeItemFromPeer(String tokenId, String objectId) {
    // Χρησιμοποιούμε το List interface για να αποφύγουμε το Type Mismatch
    List<AuctionItem> items = peerItems.get(tokenId); 
    
    if (items != null) {
        // Κλειδώνουμε μόνο τη συγκεκριμένη λίστα και όχι όλο το Map
        synchronized (items) { 
            for (int i = 0; i < items.size(); i++) {
                if (items.get(i).objectId.equals(objectId)) {
                    items.remove(i);
                    log("Removed item " + objectId + " from peer " + tokenId);
                    break;
                }
            }
        }
    }
}
   public String handleRequestAuction(String tokenId, String ipAddress, int port, String[] itemStrings) {
    synchronized (activePeers) {
        PeerInfo peer = activePeers.get(tokenId);
        if (peer == null) return "REQUEST_AUCTION_FAIL|Not logged in";
        peer.ipAddress = ipAddress;
        peer.port = port;
    }

    for (String itemStr : itemStrings) {
        // Μετατροπή String -> AuctionItem
        AuctionItem item = AuctionItem.fromProtocolString(itemStr);
        if (item != null) {
            item.sellerTokenId = tokenId;
            addItemToQueue(item); // Η addItemToQueue θα το βάλει τώρα στο σωστό peerItems Map
        }
    }
    return "REQUEST_AUCTION_OK|Items received";
    }

    // --- auction queries ---

    public String getCurrentAuction(String tokenId) {
        // grab seller token inside the lock, then release it before calling checkActive
        // this way we don't block bid processing while pinging the seller
        String seller;
        synchronized (auctionLock) {
            if (currentObjectId == null) {
                return "NO_AUCTION|No active auction";
            }
            seller = sellerTokenId;
        }

        // check if seller is still online (this can take up to CHECK_ACTIVE_TIMEOUT)
        if (!checkActive(seller)) {
            return "NO_AUCTION|Auction cancelled - seller offline";
        }

        // re-enter the lock to read auction info (could have changed while we were checking)
        synchronized (auctionLock) {
            if (currentObjectId == null) {
                return "NO_AUCTION|No active auction";
            }
            return "CURRENT_AUCTION|" + currentObjectId + "|" + currentDescription;
        }
    }

    public String getAuctionDetails(String tokenId) {
        synchronized (auctionLock) {
            if (currentObjectId == null) {
                return "NO_AUCTION|No active auction";
            }

            long timeLeft = (auctionEndTime - System.currentTimeMillis()) / 1000;
            if (timeLeft < 0) timeLeft = 0;

            String bidder = (highestBidderTokenId != null) ? highestBidderTokenId : "";
            return "AUCTION_DETAILS|" + sellerTokenId + "|" + currentBid + "|" + timeLeft + "|" + bidder;
        }
    }

    // --- bidding ---

    public String placeBid(String tokenId, String objectId, double bidAmount) {
        synchronized (auctionLock) {
            if (currentObjectId == null || !currentObjectId.equals(objectId)) {
                return "BID_FAIL|No active auction for this item";
            }

            // check if auction has ended
            if (System.currentTimeMillis() >= auctionEndTime) {
                return "BID_FAIL|Auction has ended";
            }

            if (bidAmount <= currentBid) {
                return "BID_FAIL|Bid too low, current highest is " + currentBid;
            }

            // accept the bid
            currentBid = bidAmount;
            highestBidderTokenId = tokenId;

            log("New bid on " + objectId + ": " + bidAmount + " by " + tokenId);
        }

        // notify all active peers about the new bid (outside the lock to avoid holding it too long)
        broadcastToAll("BID_UPDATE|" + objectId + "|" + bidAmount + "|" + tokenId);

        return "BID_OK|Bid accepted";
    }

    // --- check if a peer is still online ---

    public boolean checkActive(String tokenId) {
        PeerInfo peer;
        synchronized (activePeers) {
            peer = activePeers.get(tokenId);
        }
        if (peer == null) return false;

        try (Socket checkSocket = new Socket()) {
            checkSocket.connect(new InetSocketAddress(peer.ipAddress, peer.port), Config.CHECK_ACTIVE_TIMEOUT);
            checkSocket.setSoTimeout(Config.CHECK_ACTIVE_TIMEOUT);

            DataOutputStream out = new DataOutputStream(checkSocket.getOutputStream());
            DataInputStream in = new DataInputStream(checkSocket.getInputStream());

            MessageHelper.sendMessage(out, "CHECK_ACTIVE|ping");
            String response = MessageHelper.receiveMessage(in);

            if (response != null && response.startsWith("CHECK_ACTIVE_ACK")) {
                return true;
            }
        } catch (IOException e) {
            log("Peer " + tokenId + " is not responding: " + e.getMessage());
        }

        // peer is offline - remove and cancel auction if they're the seller
        handlePeerDisconnect(tokenId);
        return false;
    }

    // handle when a peer goes offline
    public void handlePeerDisconnect(String tokenId) {
        synchronized (activePeers) {
            activePeers.remove(tokenId);
        }
        synchronized (peerItems) {
            peerItems.remove(tokenId);
        }

        // if this peer was the current seller, cancel the auction
        synchronized (auctionLock) {
            if (tokenId.equals(sellerTokenId)) {
                String cancelledObject = currentObjectId;
                currentObjectId = null;
                currentDescription = null;
                sellerTokenId = null;
                currentBid = 0;
                highestBidderTokenId = null;
                auctionEndTime = 0;

                log("Auction cancelled for " + cancelledObject + " - seller disconnected");
                broadcastToAll("AUCTION_CANCELLED|" + cancelledObject + "|Seller disconnected");
            }
        }
    }

    // --- broadcasting ---

    // send a message to all active peers
    public void broadcastToAll(String message) {
        ArrayList<PeerInfo> peers;
        synchronized (activePeers) {
            peers = new ArrayList<>(activePeers.values());
        }

        for (PeerInfo peer : peers) {
            sendToPeer(peer, message);
        }
    }

    // send a message to a specific peer by opening a short-lived connection
    public void sendToPeer(PeerInfo peer, String message) {
        if (peer.port == 0) return; // peer hasn't sent their port yet

        try {
            Socket socket = new Socket(peer.ipAddress, peer.port);
            DataOutputStream out = new DataOutputStream(socket.getOutputStream());
            MessageHelper.sendMessage(out, message);
            socket.close();
        } catch (IOException e) {
            log("Could not reach peer " + peer.username + " at " + peer.ipAddress + ":" + peer.port);
        }
    }

    // send a message to a peer by tokenId
    public void sendToPeer(String tokenId, String message) {
        PeerInfo peer;
        synchronized (activePeers) {
            peer = activePeers.get(tokenId);
        }
        if (peer != null) {
            sendToPeer(peer, message);
        }
    }

    // --- utility ---

    // update the seller/bidder counters in registeredUsers
    public void incrementCounter(String tokenId, boolean isSeller) {
        String username = null;
        synchronized (activePeers) {
            PeerInfo peer = activePeers.get(tokenId);
            if (peer != null) {
                if (isSeller) {
                    peer.numAuctionsSeller++;
                } else {
                    peer.numAuctionsBidder++;
                }
                username = peer.username;
            }
        }

        // also update the registered users record
        String[] userData = registeredUsers.get(username);

        if (userData != null) {
            // Κλειδώνουμε ΜΟΝΟ τον συγκεκριμένο πίνακα δεδομένων του χρήστη.
            // Έτσι, αν την ίδια στιγμή ενημερώνεται ένας ΑΛΛΟΣ χρήστης, δεν περιμένει καθόλου.
            synchronized (userData) { 
                if (isSeller) {
                    int currentVal = Integer.parseInt(userData[1]);
                    userData[1] = String.valueOf(currentVal + 1);
                } else {
                    int currentVal = Integer.parseInt(userData[2]);
                    userData[2] = String.valueOf(currentVal + 1);
                }
            }
        }
    }

    public void log(String msg) {
        String time = new java.text.SimpleDateFormat("HH:mm:ss").format(new Date());
        System.out.println("[SERVER " + time + "] " + msg);
    }
}
