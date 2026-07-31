import requests
import sys
import json

def transcribe(server_url, audio_path, model_name="Qwen3-ASR-1.7B"):
    url = f"{server_url}/v1/audio/transcriptions"
    files = {"file": open(audio_path, "rb")}
    data = {"model": model_name}

    print(f"Sending audio: {audio_path}")
    response = requests.post(url, files=files, data=data, timeout=300)
    files["file"].close()

    if response.status_code == 200:
        result = response.json()
        print(f"\nRecognition result:\n{result.get('text', result)}")
        return result
    else:
        print(f"Error {response.status_code}: {response.text}")
        return None

if __name__ == "__main__":
    server_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    audio_path = sys.argv[2] if len(sys.argv) > 2 else "test.wav"
    model = sys.argv[3] if len(sys.argv) > 3 else "Qwen3-ASR-1.7B"

    transcribe(server_url, audio_path, model)
