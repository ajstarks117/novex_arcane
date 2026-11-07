import urllib.request

url_https = 'https://sespp-106-216-244-114.run.pinggy-free.link/webhook'
url_http = 'http://sespp-106-216-244-114.run.pinggy-free.link/webhook'
headers = {'Content-Type': 'application/json'}
data = b'{"test":"data"}'

for url in [url_http, url_https]:
    print(f"Testing {url} ...")
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        print("Success:", resp.status)
    except Exception as e:
        print("Error:", type(e), e)
