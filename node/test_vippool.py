import socket
import json

def test_vippool():
    host = "stratum1.vippool.net"
    port = 8888
    print(f"Connecting to {host}:{port}...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(8.0)
        s.connect((host, port))
        print("TCP Connected OK!")

        # Send mining.subscribe
        req = {"id": 1, "method": "mining.subscribe", "params": ["MonaMiner/2.1.0"]}
        msg = json.dumps(req) + "\n"
        print("Sending:", msg.strip())
        s.sendall(msg.encode("utf-8"))

        data = s.recv(4096)
        print("Received Subscribe Response:", data.decode("utf-8", errors="ignore").strip())

        # Test auth with dummy user
        req_auth = {"id": 2, "method": "mining.authorize", "params": ["testuser.worker1", "x"]}
        msg_auth = json.dumps(req_auth) + "\n"
        print("Sending Auth:", msg_auth.strip())
        s.sendall(msg_auth.encode("utf-8"))

        data2 = s.recv(4096)
        print("Received Auth Response:", data2.decode("utf-8", errors="ignore").strip())

        s.close()
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test_vippool()
