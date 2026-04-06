import java.io.*;
import java.util.*;

// generates random auction items at random intervals (RAND * 120 seconds)
// saves them as files in the peer's shared_directory
public class ObjectGenerator extends Thread {

    private Peer peer;
    private boolean running = true;
    private int itemCounter = 0;

    // some random descriptions to pick from
    private static final String[] DESCRIPTIONS = {
        "Vintage watch",
        "Old painting",
        "Rare coin collection",
        "Antique vase",
        "Signed football",
        "Retro camera",
        "Vinyl record collection",
        "Handmade jewelry",
        "Classic book first edition",
        "Ceramic sculpture"
    };

    private Random rand = new Random();

    public ObjectGenerator(Peer peer) {
        this.peer = peer;
        this.setDaemon(true);
    }

    public void stopRunning() {
        running = false;
        this.interrupt();
    }

    @Override
    public void run() {
        while (running) {
            try {
                // wait a random time: RAND * 120 seconds
                long waitTime = (long) (Math.random() * Config.MAX_ITEM_INTERVAL * 1000);
                Thread.sleep(waitTime);

                if (!running) break;

                // create the item
                itemCounter++;
                String objectId = peer.username + "_Object_" + String.format("%02d", itemCounter);
                String description = DESCRIPTIONS[rand.nextInt(DESCRIPTIONS.length)];
                double startBid = 10 + rand.nextInt(191); // 10 to 200
                int diarkeia = 60 + rand.nextInt(121);     // 60 to 180 seconds

                AuctionItem item = new AuctionItem(objectId, description, startBid, diarkeia);

                // save to shared_directory
                String filePath = peer.sharedDir + "/" + objectId + ".txt";
                item.saveToFile(filePath);

                synchronized (peer.myItems) {
                    peer.myItems.add(objectId);
                }

                peer.log("Generated new item: " + item);

                // if we're logged in, send it to the server
                if (peer.getTokenId() != null) {
                    peer.sendNewItem(item);
                }

            } catch (InterruptedException e) {
                if (!running) break;
            } catch (IOException e) {
                peer.log("Error saving item file: " + e.getMessage());
            }
        }
    }
}
