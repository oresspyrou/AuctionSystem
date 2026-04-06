import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.net.Socket;

// handles sending and receiving messages over TCP sockets
// uses writeUTF/readUTF which adds a 2-byte length prefix automatically
public class MessageHelper {

    public static void sendMessage(DataOutputStream out, String msg) throws IOException {
        out.writeUTF(msg);
        out.flush();
    }

    public static String receiveMessage(DataInputStream in) throws IOException {
        return in.readUTF();
    }

    // convenience: open streams from a socket, send a message, read the response, close
    public static String sendAndReceive(Socket socket, String msg) throws IOException {
        DataOutputStream out = new DataOutputStream(socket.getOutputStream());
        DataInputStream in = new DataInputStream(socket.getInputStream());
        sendMessage(out, msg);
        return receiveMessage(in);
    }
}
