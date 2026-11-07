import urllib.request, json
req = urllib.request.Request('https://sespp-106-216-244-114.run.pinggy-free.link/webhook', data=b'{"repository":{"full_name":"test/repo"}}', headers={'Content-Type': 'application/json', 'X-Hub-Signature-256': 'sha256=invalid', 'X-Github-Event': 'push'})
try:
    print(urllib.request.urlopen(req).read())
except Exception as e:
    print(e)
