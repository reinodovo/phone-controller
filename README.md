# Phone Controller

Lets any service control an Android phone over a websocket and records the session.

- **controller** (`src/controller`): owns the phone through an adb server, hands out exclusive sessions, runs actions, records every session and serves a viewer.
- **SDK** (import name `phone`): the library services use to talk to the controller.

```python
import phone

with phone.session("my-service") as p:
    print(p.url)  # the session's page in the viewer
    p.tap(360, 740)
```

## Sessions

- Only one session holds the phone at a time and they are enqueued.
- A session ends when the client closes the `with` block or disconnects, or after 60s without a call
  (time spent running a call doesn't count). `phone.session(..., debug=True)` turns the idle timeout off.
- Every session **starts** with the phone unlocked and in the home screen.
- Every session **ends** with a force-stop of every app the session opened (plus the app in front at the time of session close), going home and locking the phone.

## Actions

| SDK | What it does |
|---|---|
| `p.open_app(package, activity=None)` | starts an app (its launcher activity if none is given) |
| `p.close_app(package)` | force-stops an app |
| `p.tap(x, y)` | taps a point |
| `p.tap_element(timeout=10, **selector)` | waits for an element and taps its center; returns the element |
| `p.type(text)` | types ASCII text |
| `p.swipe(x1, y1, x2, y2, duration=0.3)` | swipes |
| `p.back()`, `p.home()` | presses Back / Home |
| `p.unlock()`, `p.lock()` | wakes and unlocks / turns the screen off (not needed at the start and end of sessions) |
| `p.dump()` | the screen's elements: `{package, activity, pid, elements: [{text, id, desc, class, package, clickable, bounds}]}` |
| `p.wait_for({name: selector, ...}, timeout=15)` | waits until any selector matches; returns `{matched: name or None, element}` |
| `p.wait_gone(timeout=15, **selector)` | waits until nothing matches the selector; returns whether it went away |
| `p.current_app()` | `{package, activity, pid}` of the app in front |
| `p.is_playing()` | whether the app in front is playing media |

Selectors are dicts:

| Key | Matches |
|---|---|
| `id` | resource id, full (`com.app:id/x`) or short (`x`) |
| `text`, `text_contains`, `text_starts`, `text_matches` | element text: exact, substring, prefix, regex |
| `desc`, `desc_contains`, `desc_starts`, `desc_matches` | content description, likewise |
| `class`, `package`, `clickable` | element class, owning app, clickability |
| `activity`, `app` | (in `wait_for`) the activity / package in front |

A failed action raises `phone.PhoneError`. With `PHONE_CONTROLLER_PAYMENT_CHECK` on, the controller also checks for a Play Store payment screen after each action, and if one shows up it presses Back and fails that action.

## Recording and viewer

Every session is stored under `$PHONE_CONTROLLER_DATA/sessions/<session id>/`: `session.json`, `steps.jsonl` (one line per step) and images:

- before `tap`, `tap_element` and `swipe`: a screenshot with the target marked, or a layout drawn from a UI dump when the screen blocks screenshots
- for `dump`: the XML plus the dump drawn over a screenshot (or on its own when screenshots are blocked)

Steps are either `user` (the client's calls) or `internal` (calls the controller makes itself, linked to the user step that caused them): every dump taken while `tap_element`, `wait_for` and `wait_gone` poll the screen (drawn as a layout only, without a screenshot), the payment check after each action (when enabled), and the unlock and clean-up around the session.

The viewer is served on the controller's port: `/` lists sessions, `/sessions/<id>` shows a session's steps and images (`?steps=user` hides internal steps).

## Running

Needs an adb server on `localhost:5037` with the phone connected and authorized (USB debugging).

```bash
uv sync                                              # .venv with the controller and the SDK
uv run python -m controller
uv run python examples/session.py                   # in another terminal
```

| Variable | Default | Used by |
|---|---|---|
| `PHONE_CONTROLLER_HOST` | `localhost` | controller: comma-separated addresses to listen on |
| `PHONE_CONTROLLER_PORT` | `8765` | controller: websocket and viewer port |
| `PHONE_CONTROLLER_PUBLIC_URL` | `http://localhost:<port>` | controller: viewer address used in the session links given to clients |
| `PHONE_CONTROLLER_IDLE_TIMEOUT` | `60` | controller: seconds without a call before a session is closed |
| `PHONE_CONTROLLER_PAYMENT_CHECK` | off | controller: `true` checks for a Play Store payment screen after each action, presses Back and fails the action |
| `PHONE_CONTROLLER_DATA` | `data` (`/data` in the image) | controller: where sessions are stored |
| `PHONE_CONTROLLER_RETENTION_DAYS` | `14` | controller: sessions older than this are deleted (checked hourly; `0` keeps all) |
| `PHONE_PASSWORD` | none | controller: the phone's lock screen password or PIN; typed (then Enter) when unlocking, only if a secure lock screen is showing |
| `PHONE_SERIAL` | first connected non-emulator device | controller: which phone to use |
| `LOG_FORMAT` | `console` on a terminal, `json` otherwise | controller: log output |
| `PHONE_CONTROLLER_URL` | `ws://localhost:8765` | SDK: controller to connect to |

Install only the SDK in another project, pinned to a release:

```bash
uv add "phone-sdk @ git+https://github.com/reinodovo/phone-controller@v0.2.0#subdirectory=sdk"
```

## Versions

The controller and the SDK share one version (`version` in `pyproject.toml` and `sdk/pyproject.toml`). When a session opens, the SDK sends its version and the controller sends its own back: they only work together within the same series, which is the major version from 1.0 on and the minor version before that (`0.2.x` works with `0.2.x`, `1.x` with `1.x`). The controller refuses an SDK of another series (or one that doesn't send a version) before queueing it. Start a new series (bump the minor while on 0.x, the major after) when a change to the protocol breaks older SDKs or controllers.

To release, set the same version in both `pyproject.toml` files, run `uv lock`, commit, then tag and push:

```bash
git tag v0.2.1 && git push origin v0.2.1
```

## Images

- `ghcr.io/reinodovo/phone-controller`: the controller
- `ghcr.io/reinodovo/adb-server`: an adb server listening on `localhost:5037`

Both are built from version tags (`v0.2.1`) and tagged with the version and its minor series (`0.2.1`, `0.2`); from 1.0 on also the major (`1`). The build fails if the tag doesn't match the versions in `pyproject.toml`.

Both are meant for host networking on the machine the phone is plugged into. The adb server needs `privileged: true`, `/dev/bus/usb` and the authorized adb key mounted at `/root/.android` (`adbkey`, `adbkey.pub`).

## Development

```bash
uv sync
uvx ruff check && uvx ruff format
```
