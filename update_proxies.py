import os
import requests

def fetch_and_save_proxies():
    # We will grab HTTPS and SOCKS5 proxies since Steam endpoints require SSL
    urls = [
        "https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/http_ssl.txt",
        "https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/socks5_all.txt",
        "https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/top-http.txt"
    ]
    
    unique_proxies = set()
    
    print("Fetching fresh public proxy lists...")
    for url in urls:
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                lines = response.text.strip().split("\n")
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Clean up protocol prefixes (like 'http://' or 'socks5://') if they exist
                    if "://" in line:
                        line = line.split("://")[1]
                        
                    # Basic validation: ensure it looks like IP:PORT
                    if ":" in line and not line.startswith("#"):
                        unique_proxies.add(line)
        except Exception as e:
            print(f"Skipping source {url} due to error: {e}")

    # Define your path to proxies.txt
    # (Adjust this string if proxies.txt is located inside a 'src' folder or elsewhere)
    file_path = os.path.join(os.path.dirname(__file__), "proxies.txt")
    
    with open(file_path, "w", encoding="utf-8") as f:
        for proxy in sorted(unique_proxies):
            f.write(f"{proxy}\n")
            
    print(f"Success! Saved {len(unique_proxies)} unique proxies to {file_path}")

if __name__ == "__main__":
    fetch_and_save_proxies()