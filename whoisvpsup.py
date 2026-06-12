import requests
import json

class IPGeolocator:
    def __init__(self):
        # Using ip-api.com (Free for non-commercial use, no API key required for HTTP)
        self.base_url = "http://api.ip-api.com/json/"

    def get_country(self, ip_address):
        """
        Fetches the country name for a given IP address.
        
        Args:
            ip_address (str): The IPv4 or IPv6 address to look up.
            
        Returns:
            dict: A dictionary containing 'country', 'status', and potentially 'error'.
        """
        try:
            url = f"{self.base_url}{ip_address}"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()

            if data.get('status') == 'fail':
                return {
                    "status": "error",
                    "message": data.get('message', 'Unknown error'),
                    "ip": ip_address
                }
            
            return {
                "status": "success",
                "ip": ip_address,
                "country": data.get('country'),
                "countryCode": data.get('countryCode'),
                "regionName": data.get('regionName'),
                "city": data.get('city'),
                "isp": data.get('isp')
            }

        except requests.exceptions.Timeout:
            return {"status": "error", "message": "Request timed out"}
        except requests.exceptions.RequestException as e:
            return {"status": "error", "message": f"Network error: {str(e)}"}
        except Exception as e:
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

def main():
    print("--- IP Country Lookup Tool ---")
    print("Note: This uses a free public API. Rate limits may apply.")
    
    locator = IPGeolocator()

    while True:
        user_input = input("\nEnter an IP address (or 'quit' to exit): ").strip()
        
        if user_input.lower() in ['quit', 'exit']:
            print("Exiting...")
            break
        
        if not user_input:
            continue

        result = locator.get_country(user_input)
        
        print("\n--- Results ---")
        if result['status'] == 'success':
            print(f"IP Address : {result['ip']}")
            print(f"Country    : {result['country']} ({result['countryCode']})")
            if result.get('regionName'):
                print(f"Region     : {result['regionName']}")
            if result.get('city'):
                print(f"City       : {result['city']}")
            print(f"ISP        : {result['isp']}")
        else:
            print(f"Error: {result['message']}")

if __name__ == "__main__":
    main()
