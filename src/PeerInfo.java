// holds info about a connected peer
// the server keeps one of these for each logged-in peer
public class PeerInfo {
    public String tokenId;
    public String ipAddress;
    public int port;
    public String username;
    public int numAuctionsSeller;
    public int numAuctionsBidder;

    public PeerInfo(String tokenId, String ipAddress, int port, String username) {
        this.tokenId = tokenId;
        this.ipAddress = ipAddress;
        this.port = port;
        this.username = username;
        this.numAuctionsSeller = 0;
        this.numAuctionsBidder = 0;
    }

    @Override
    public String toString() {
        return "PeerInfo{" + username + ", token=" + tokenId
                + ", " + ipAddress + ":" + port
                + ", seller=" + numAuctionsSeller + ", bidder=" + numAuctionsBidder + "}";
    }
}
