import requests

def get_ip_info(ip_address=None):
    if ip_address:
        url = f"http://ip-api.com/json/{ip_address}"
    else:
        url = "http://ip-api.com/json/"

    response = requests.get(url, timeout=5)
    data = response.json()

    if data.get("status") == "success":
        return {
            "IP": data.get("query"),
            "Country": data.get("country"),
            "Region": data.get("regionName"),
            "City": data.get("city"),
            "ZIP": data.get("zip"),
            "Latitude": data.get("lat"),
            "Longitude": data.get("lon"),
            "ISP": data.get("isp"),
            "Org": data.get("org"),
            "AS": data.get("as")
        }
    else:
        return {"error": "Failed to retrieve IP info"}

if __name__ == "__main__":
    info = get_ip_info("8.8.8.8")  # or None for your own IP
    for k, v in info.items():
        print(f"{k}: {v}")
