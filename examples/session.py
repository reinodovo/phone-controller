import time

import phone

with phone.session("examples/session") as p:
    print(f"got the phone, it's unlocked: {p.url}")
    time.sleep(3)
print("session closed, the phone is locked again")
