import urllib.request, json
req = urllib.request.Request('http://127.0.0.1:8000/webhook', data=b'{"repository":{"full_name":"test/repo"}}', headers={'Content-Type': 'application/json', 'X-Hub-Signature-256': 'sha256=invalid', 'X-Github-Event': 'push'})
try:
    print(urllib.request.urlopen(req).read())
except Exception as e:
    print(e)
