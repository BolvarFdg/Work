# Work

import java.io.*;
import java.nio.file.*;

public class PcmToWavConverter {

    public static void main(String[] args) throws IOException {
        int byteRate = 16000 * 2 * 1;
        byte[] buffer = new byte[1280];

        try (FileOutputStream outputStream = new FileOutputStream("output.wav")) {
            // write WAVE header
            outputStream.write(new byte[] {'R', 'I', 'F', 'F'});
            outputStream.write(intToBytes(0));
            outputStream.write(new byte[] {'W', 'A', 'V', 'E', 'f', 'm', 't', ' '});
            outputStream.write(intToBytes(16));
            outputStream.write(shortToBytes((short) 1));
            outputStream.write(shortToBytes((short) 1));
            outputStream.write(intToBytes(16000));
            outputStream.write(intToBytes(byteRate));
            outputStream.write(shortToBytes((short) 2));
            outputStream.write(shortToBytes((short) 16));
            outputStream.write(new byte[] {'d', 'a', 't', 'a'});
            outputStream.write(intToBytes(0));

            // continuously read data and write to file
            while (true) {
                // read data
                // you need to implement this part to read the PCM data from some source
                // the readData method should return null if there is no more data to read
                byte[] data = readData(1280);
                if (data == null) {
                    break;
                }

                // write data to file
                outputStream.write(data);
            }

            // update WAV header with data size
            long dataLength = outputStream.getChannel().size() - 44;
            outputStream.seek(4);
            outputStream.write(intToBytes((int) (dataLength + 36)));
            outputStream.seek(40);
            outputStream.write(intToBytes((int) dataLength));
        }
    }

    private static byte[] intToBytes(int value) {
        return new byte[] {
                (byte) (value & 0xff),
                (byte) ((value >> 8) & 0xff),
                (byte) ((value >> 16) & 0xff),
                (byte) ((value >> 24) & 0xff)
        };
    }

    private static byte[] shortToBytes(short value) {
        return new byte[] {
                (byte) (value & 0xff),
                (byte) ((value >> 8) & 0xff)
        };
    }

    // This method should be implemented to read the PCM data from some source
    // The method should return null if there is no more data to read
    private static byte[] readData(int length) {
        // Implement this method to read the PCM data from some source
        // In this example, we just return null to stop the program from running indefinitely
        return null;
    }
}

