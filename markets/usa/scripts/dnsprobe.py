import dns.resolver, time, random, sys
hosts = ['woocommerce.com','formula1.com','target.com','wikipedia.org','github.com','bestbuy.com','ikea.com','nytimes.com']
r = dns.resolver.Resolver(); r.lifetime = 5
while True:
    h = random.choice(hosts); t = time.time()
    try:
        r.resolve(h, 'A', raise_on_no_answer=False); ok = 'ok'
    except Exception as e:
        ok = type(e).__name__
    print(time.strftime('%H:%M:%S'), h, ok, round(time.time() - t, 2), flush=True)
    time.sleep(10)
