import time
from site_tester import run_automated_test

CHECK_INTERVAL_SECONDS = 600

print(f"?? Automated Site Tester Active. Checking site every {CHECK_INTERVAL_SECONDS // 60} minutes...")
while True:
    try:
        run_automated_test()
    except Exception as e:
        print(f"?? Test loop exception: {e}")
    time.sleep(CHECK_INTERVAL_SECONDS)
