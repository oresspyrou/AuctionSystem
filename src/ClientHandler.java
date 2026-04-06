import java.io.*;
import java.net.*;

// one thread per connected peer, handles their requests
public class ClientHandler extends Thread {

    private Socket socket;
    private AuctionServer server;

    public ClientHandler(Socket socket, AuctionServer server) {
        this.socket = socket;
        this.server = server;
    }

    @Override
    public void run() {
        try {
            DataInputStream in = new DataInputStream(socket.getInputStream());
            DataOutputStream out = new DataOutputStream(socket.getOutputStream());

            // read the request
            String message = MessageHelper.receiveMessage(in);
            String[] parts = message.split("\\|");
            String type = parts[0];

            String response = "";

            switch (type) {
                case "REGISTER":
                    response = handleRegister(parts);
                    break;

                case "LOGIN":
                    response = handleLogin(parts);
                    break;

                case "LOGOUT":
                    response = handleLogout(parts);
                    break;

                case "REQUEST_AUCTION":
                    response = handleRequestAuction(parts);
                    break;

                case "GET_CURRENT_AUCTION":
                    response = handleGetCurrentAuction(parts);
                    break;

                case "GET_AUCTION_DETAILS":
                    response = handleGetAuctionDetails(parts);
                    break;

                case "PLACE_BID":
                    response = handlePlaceBid(parts);
                    break;

                default:
                    response = "ERROR|Unknown command: " + type;
                    break;
            }

            MessageHelper.sendMessage(out, response);

        } catch (IOException e) {
            server.log("Client handler error: " + e.getMessage());
        } finally {
            try {
                socket.close();
            } catch (IOException e) {
                // nothing to do
            }
        }
    }

    // REGISTER|username|password
    private String handleRegister(String[] parts) {
        if (parts.length < 3) return "REGISTER_FAIL|Missing username or password";
        return server.register(parts[1], parts[2]);
    }

    // LOGIN|username|password
    private String handleLogin(String[] parts) {
        if (parts.length < 3) return "LOGIN_FAIL|Missing username or password";
        String ip = socket.getInetAddress().getHostAddress();
        return server.login(parts[1], parts[2], ip);
    }

    // LOGOUT|token_id
    private String handleLogout(String[] parts) {
        if (parts.length < 2) return "LOGOUT_OK|Bye";
        return server.logout(parts[1]);
    }

    // REQUEST_AUCTION|token_id|ip|port|item1;desc;bid;dur|item2;desc;bid;dur|...
    private String handleRequestAuction(String[] parts) {
        if (parts.length < 4) return "REQUEST_AUCTION_FAIL|Invalid format";

        String tokenId = parts[1];
        String ip = parts[2];
        int port;
        try {
            port = Integer.parseInt(parts[3]);
        } catch (NumberFormatException e) {
            return "REQUEST_AUCTION_FAIL|Invalid port";
        }

        // items start from index 4
        String[] items = new String[parts.length - 4];
        for (int i = 4; i < parts.length; i++) {
            items[i - 4] = parts[i];
        }

        return server.handleRequestAuction(tokenId, ip, port, items);
    }

    // GET_CURRENT_AUCTION|token_id
    private String handleGetCurrentAuction(String[] parts) {
        if (parts.length < 2) return "NO_AUCTION|Missing token";
        return server.getCurrentAuction(parts[1]);
    }

    // GET_AUCTION_DETAILS|token_id
    private String handleGetAuctionDetails(String[] parts) {
        if (parts.length < 2) return "NO_AUCTION|Missing token";
        return server.getAuctionDetails(parts[1]);
    }

    // PLACE_BID|token_id|object_id|bid_amount
    private String handlePlaceBid(String[] parts) {
        if (parts.length < 4) return "BID_FAIL|Invalid format";

        String tokenId = parts[1];
        String objectId = parts[2];
        double bidAmount;
        try {
            bidAmount = Double.parseDouble(parts[3]);
        } catch (NumberFormatException e) {
            return "BID_FAIL|Invalid bid amount";
        }

        return server.placeBid(tokenId, objectId, bidAmount);
    }
}
