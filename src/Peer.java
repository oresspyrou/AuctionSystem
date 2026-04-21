import java.io.*;
import java.net.*;
import java.util.*;

public class Peer {

    String username;
    String password;
    String tokenId = null;
    String sharedDir;
    int peerPort; // port our PeerServer listens on

    // keep track of our own items so we don't bid on them
    ArrayList<String> myItems = new ArrayList<>();

    PeerServer peerServer;
    ObjectGenerator objectGenerator;
    AuctionPoller auctionPoller;

    public Peer(String username, String password) {
        this.username = username;
        this.password = password;
        this.sharedDir = "shared_directories/" + username;

        // make sure the shared directory exists
        new File(sharedDir).mkdirs();
    }

    public static void main(String[] args) {
        if (args.length < 2) {
            System.out.println("Usage: java Peer <username> <password> [auto]");
            return;
        }

        Peer peer = new Peer(args[0], args[1]);

        // start the peer's server socket on a random port
        peer.startPeerServer();

        // start generating items in the background
        peer.startObjectGenerator();

        // if "auto" is passed, do register + login + polling automatically
        if (args.length >= 3 && args[2].equals("auto")) {
            peer.autoRun();
        } else {
            peer.cliLoop();
        }
    }

    private void startPeerServer() {
        peerServer = new PeerServer(this);
        peerServer.start();
        peerPort = peerServer.getPort();
        log("PeerServer listening on port " + peerPort);
    }

    private void startObjectGenerator() {
        objectGenerator = new ObjectGenerator(this);
        objectGenerator.start();
    }

    // auto mode: register, login, start polling - for demo/testing
    private void autoRun() {
        log("Running in auto mode...");

        // try to register (might fail if already registered, that's ok)
        String regResult = sendToServer("REGISTER|" + username + "|" + password);
        log("Register: " + regResult);

        // login
        doLogin();

        // keep running until interrupted
        try {
            while (true) {
                Thread.sleep(5000);
            }
        } catch (InterruptedException e) {
            doLogout();
        }
    }

    // interactive CLI
    private void cliLoop() {
        Scanner scanner = new Scanner(System.in);
        log("Commands: register, login, logout, status, exit");

        while (true) {
            System.out.print("> ");
            String command = scanner.nextLine().trim().toLowerCase();

            switch (command) {
                case "register":
                    String regResult = sendToServer("REGISTER|" + username + "|" + password);
                    log("Register: " + regResult);
                    break;

                case "login":
                    doLogin();
                    break;

                case "logout":
                    doLogout();
                    break;

                case "status":
                    printStatus();
                    break;

                case "exit":
                    doLogout();
                    log("Shutting down...");
                    objectGenerator.stopRunning();
                    peerServer.stopRunning();
                    scanner.close();
                    System.exit(0);
                    break;

                default:
                    log("Unknown command. Try: register, login, logout, status, exit");
                    break;
            }
        }
    }

    private void doLogin() {
        String response = sendToServer("LOGIN|" + username + "|" + password);
        log("Login: " + response);

        if (response != null && response.startsWith("LOGIN_OK")) {
            String[] parts = response.split("\\|");
            synchronized (this) {
                tokenId = parts[1];
            }
            log("Logged in with token: " + tokenId);

            // send existing items in shared_directory to the server
            sendExistingItems();

            // start polling for auctions
            auctionPoller = new AuctionPoller(this);
            auctionPoller.start();
        }
    }

    private void doLogout() {
        String token = getTokenId();
        if (token == null) {
            log("Not logged in");
            return;
        }

        String response = sendToServer("LOGOUT|" + token);
        log("Logout: " + response);

        synchronized (this) {
            tokenId = null;
        }

        if (auctionPoller != null) {
            auctionPoller.stopRunning();
            auctionPoller = null;
        }
    }

    // scan shared_directory and send all existing items to the server
    private void sendExistingItems() {
        File dir = new File(sharedDir);
        File[] files = dir.listFiles();
        if (files == null || files.length == 0) return;

        StringBuilder itemsStr = new StringBuilder();
        for (File f : files) {
            if (!f.getName().endsWith(".txt")) continue;
            try {
                AuctionItem item = AuctionItem.parseFromFile(f.getAbsolutePath());
                if (item != null) {
                    synchronized (myItems) {
                        myItems.add(item.objectId);
                    }
                    if (itemsStr.length() > 0) itemsStr.append("|");
                    itemsStr.append(item.toProtocolString());
                }
            } catch (IOException e) {
                log("Error reading file: " + f.getName());
            }
        }

        if (itemsStr.length() > 0) {
            String myIp = getMyIpAddress();
            String msg = "REQUEST_AUCTION|" + getTokenId() + "|" + myIp + "|" + peerPort + "|" + itemsStr;
            String response = sendToServer(msg);
            log("Sent existing items to server: " + response);
        }
    }

    // send a single new item to the server
    public void sendNewItem(AuctionItem item) {
        String token = getTokenId();
        if (token == null) return;

        String msg = "REQUEST_AUCTION|" + token + "|" + getMyIpAddress() + "|" + peerPort + "|" + item.toProtocolString();
        String response = sendToServer(msg);
        log("Sent new item " + item.objectId + " to server: " + response);
    }

    private void printStatus() {
        String token = getTokenId();
        log("Username: " + username);
        log("Token: " + (token != null ? token : "not logged in"));
        log("PeerServer port: " + peerPort);
        log("Shared directory: " + sharedDir);

        File dir = new File(sharedDir);
        File[] files = dir.listFiles();
        int count = (files != null) ? files.length : 0;
        log("Items in shared_directory: " + count);
    }

    private String getMyIpAddress() {
        try {
            return InetAddress.getLocalHost().getHostAddress();
        } catch (UnknownHostException e) {
            return "127.0.0.1";
        }
    }

    // open a connection to the server, send a message, get the response
    public String sendToServer(String msg) {
        try {
            Socket socket = new Socket(Config.SERVER_HOST, Config.SERVER_PORT);
            String response = MessageHelper.sendAndReceive(socket, msg);
            socket.close();
            return response;
        } catch (IOException e) {
            log("Could not connect to server: " + e.getMessage());
            return null;
        }
    }

    // thread-safe getter for tokenId
    public synchronized String getTokenId() {
        return tokenId;
    }

    public void log(String msg) {
        String time = new java.text.SimpleDateFormat("HH:mm:ss").format(new Date());
        System.out.println("[PEER:" + username + " " + time + "] " + msg);
    }
}
